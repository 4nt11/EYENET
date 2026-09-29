# SPDX-License-Identifier: AGPL-3.0-or-later
"""`CollectorSupervisor` — the in-process discovery runtime (API_PLAN §4.12.4, M9.E3).

A tick-driven reconciler (NOT a systemd flag-watcher). Each tick it:

1. **Reconciles collector state** — drives ``observed_state`` toward
   ``desired_state`` (the operator's intent), emitting
   ``eyenet.audit.collector.reconciled`` on every transition. Polling storage
   makes this crash-safe by construction: a restarted supervisor resumes from
   the persisted ``observed_state``, no in-memory state to lose.
2. **Dispatches approved joins** — for each ``approved`` candidate with an
   assigned collector, it runs the real §4.12.3 eligibility predicate, leases a
   scout identity, writes ``approved → joining``, and records a
   :class:`~eyenet.contracts.supervisor.JoinGroupCommand` in the
   ``eyenet.audit.candidate.joining`` payload.

The actual platform join (``joining → joined``) and the command's bus dispatch
are the collector's job in E5; the supervisor's responsibility ends at the
eligibility gate + scout lease + ``joining`` transition.
"""

from __future__ import annotations

import asyncio
import sys
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from eyenet.contracts.audit_subjects import AuditSubject
from eyenet.contracts.collector import compute_instance_id
from eyenet.contracts.enums import (
    ArtifactValidationState,
    CandidateState,
    CollectorDesiredState,
    CollectorObservedState,
    GroupAccessKind,
    IdentityState,
)
from eyenet.contracts.supervisor import BackfillCommand, JoinGroupCommand, command_subject_for
from eyenet.service import ServiceBase
from eyenet.services.discovery.eligibility import CollectorEligibilityResult, collector_eligibility
from eyenet.telemetry.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Iterable
    from uuid import UUID

    from eyenet.contracts.access_artifact import GroupAccessArtifactRow
    from eyenet.contracts.bus import Bus
    from eyenet.contracts.candidate import GroupCandidateRow
    from eyenet.contracts.collector import CollectorRow
    from eyenet.contracts.identity import IdentityRow
    from eyenet.contracts.source import SourceRow
    from eyenet.storage.repository import BaseRepository

_log = get_logger()
_APPROVED_BATCH = 1000

# Post-crash backoff: a crashed collector cools for min(2^restart_count, 600)s
# before the supervisor respawns it (matches CollectorObservedState.COOLING's
# documented semantics). This is the crash-loop guard that keeps a wedged
# collector from hammering the platform (and getting the account banned).
_MAX_COOLING_S = 600.0

# Access-artifact selection preference (M9.E5.5): cheapest / lowest-OPSEC kind
# first. Only kinds the collector can currently action are listed — an
# artifact of any other kind (or none usable) falls through to the
# public-identifier path (``access_artifact_id=None`` on ``platform_groupid``),
# which never fails worse than dispatching an artifact the collector would
# reject outright. Extend in lockstep with ``telegram._join.select_join_action``
# as more kinds gain support.
_KIND_PREFERENCE: tuple[GroupAccessKind, ...] = (
    GroupAccessKind.PUBLIC_IDENTIFIER,
    GroupAccessKind.INVITE_LINK,
)
_USABLE_VALIDATION_STATES = frozenset(
    {ArtifactValidationState.VALID, ArtifactValidationState.UNVERIFIED}
)


def select_access_artifact(
    artifacts: Iterable[GroupAccessArtifactRow],
) -> GroupAccessArtifactRow | None:
    """Pick the cheapest usable access artifact for a join, or ``None`` for the
    public-identifier fallback (M9.E5.5, §4.12.4).

    Usable = ``validation_state`` in {VALID, UNVERIFIED}, NOT
    ``requires_admin_approval``, and a kind the collector can action (present in
    :data:`_KIND_PREFERENCE`). Ranked by preference order; ties broken
    deterministically by artifact id so selection is stable across ticks.
    """
    usable = [
        art
        for art in artifacts
        if art.validation_state in _USABLE_VALIDATION_STATES
        and not art.requires_admin_approval
        and art.kind in _KIND_PREFERENCE
    ]
    if not usable:
        return None
    return min(usable, key=lambda a: (_KIND_PREFERENCE.index(a.kind), a.id))


class CollectorSupervisor(ServiceBase):
    """Tick-driven collector-state reconciler + approved-join dispatcher (M9.E3).

    ``reconcile_collectors`` now actually SPAWNS the collector process (control
    plane meets data plane): when ``desired_state`` is RUNNING the supervisor
    launches ``python -m eyenet.cli collector --identity ... --type ...`` as a
    child, tracks the handle, and drives ``observed_state`` from real process
    liveness (RUNNING while alive, CRASHED + COOLING on unexpected exit, STOPPED
    when the operator stops it). The child inherits the supervisor's env
    (EYENET_NATS_URL / EYENET_DATA_DIR / EYENET_IDENTITIES), so it must run in an
    image that carries the collector deps + data volume (eyenet:base).

    In-memory ``_procs`` is rebuilt lazily: a restarted supervisor finds no
    handles, sees ``desired=RUNNING`` with no live child, and respawns — so
    recovery stays crash-safe by construction.
    """

    def __init__(self, *, bus: Bus, storage: BaseRepository) -> None:
        super().__init__(bus=bus, storage=storage)
        # collector_id -> live child process.
        self._procs: dict[UUID, asyncio.subprocess.Process] = {}
        # collector_id -> monotonic deadline before a crashed collector respawns.
        self._cooling_until: dict[UUID, float] = {}

    def _monotonic(self) -> float:
        """Monotonic-clock seam (overridable in tests) for the cooling backoff."""
        return time.monotonic()

    def _wall_now(self) -> datetime:
        """Wall-clock seam (overridable in tests) for the heartbeat stamp."""
        return datetime.now(tz=UTC)

    async def _heartbeat(self, collector: CollectorRow) -> None:
        """Stamp ``last_heartbeat_at`` every tick a child is confirmed alive.

        Audits the RUNNING transition only when the observed_state actually
        changes (via :meth:`_set_observed`); a steady collector just refreshes
        the heartbeat with no audit spam. The heartbeat is supervisor-observed
        process liveness — the same signal reconcile already computes.

        # ponytail: process-alive is the heartbeat; a wedged-but-alive collector
        # still beats. Collector self-report (last actual ingest) is the upgrade
        # path if we ever need to distinguish "up" from "up and pulling".
        """
        now = self._wall_now()
        if collector.observed_state is not CollectorObservedState.RUNNING:
            await self._set_observed(
                collector, CollectorObservedState.RUNNING, last_heartbeat_at=now
            )
        else:
            await self._storage.record_collector_observed_state(
                collector_id=collector.id,
                observed_state=CollectorObservedState.RUNNING,
                last_heartbeat_at=now,
            )

    async def _spawn(self, collector: CollectorRow) -> asyncio.subprocess.Process | None:
        """Launch the collector child process. Returns the handle, or None if the
        identity is missing or the OS refused the spawn."""
        ident = await self._storage.get_identity(collector.identity_id)
        if ident is None:
            _log.error("supervisor.spawn_no_identity", collector_id=str(collector.id))
            return None
        # Stale-claim recovery: the identity claim (IdentityState.IN_USE) has no
        # liveness lease, so a hard-killed child (e.g. on supervisor restart)
        # leaves it IN_USE and every respawn then dies with "identity already in
        # use". This supervisor owns the collector process lifecycle and is about
        # to (re)spawn this collector with no live child holding the claim, so a
        # lingering IN_USE is stale — clear it to AVAILABLE so the child can claim
        # on boot. COOLING/FROZEN/BURNED are honored (real cooldowns/bans).
        # ponytail: assumes a single supervisor owns the fleet (small-operator
        # default cardinality 1); a multi-supervisor deployment needs a real lease.
        if ident.state is IdentityState.IN_USE:
            _log.info(
                "supervisor.stale_claim_cleared",
                identity=ident.name,
                collector_id=str(collector.id),
            )
            await self._storage.set_identity_state(
                identity_id=ident.id, state=IdentityState.AVAILABLE
            )
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "eyenet.cli",
                "collector",
                "--identity",
                ident.name,
                "--type",
                collector.kind.value,
            )
        except OSError as exc:
            _log.error("supervisor.spawn_failed", collector_id=str(collector.id), error=str(exc))
            return None
        _log.info(
            "supervisor.collector_spawned",
            collector_id=str(collector.id),
            pid=proc.pid,
            identity=ident.name,
            kind=collector.kind.value,
        )
        return proc

    async def _set_observed(
        self,
        collector: CollectorRow,
        new_state: CollectorObservedState,
        *,
        restart_count: int | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
        last_heartbeat_at: datetime | None = None,
    ) -> None:
        """Write + audit an observed_state transition, but only when something
        actually changed (no per-tick audit spam for a steady collector). A
        CRASHED transition must carry an error breadcrumb pair (CHECK-enforced)."""
        unchanged_count = restart_count is None or restart_count == collector.restart_count
        if collector.observed_state is new_state and unchanged_count:
            return
        await self._storage.record_collector_observed_state(
            collector_id=collector.id,
            observed_state=new_state,
            restart_count=restart_count,
            last_error_type=error_type,
            last_error_message=error_message,
            last_heartbeat_at=last_heartbeat_at,
        )
        await self.audit.emit(
            event=AuditSubject.COLLECTOR_RECONCILED.value,
            subject_kind="collector",
            subject_id=collector.id,
            payload={
                "from": collector.observed_state.value,
                "to": new_state.value,
                "desired": collector.desired_state.value,
            },
        )

    @property
    def name(self) -> str:
        return "collector_supervisor"

    @property
    def instance_id(self) -> str:
        return "supervisor_default"

    async def on_subscribe(self) -> None:
        """No bus subscription in v1 — the supervisor is purely tick-driven
        (the candidate.* lifecycle bus channel + operator stream is Group H).
        Polling storage each tick is crash-safe by construction."""

    async def tick(self) -> None:
        await self.reconcile_collectors()
        await self.dispatch_approved()
        await self.dispatch_backfills()

    async def dispatch_backfills(self) -> None:
        """Dispatch a one-shot backfill to any collector whose config carries the
        ``_backfill_pending`` flag (set via PATCH /v1/collectors/{id} backfill=true)
        and which is a live child of this supervisor, then clear the flag.

        The collector's ``_run_backfill`` is scoped to its monitored groups, so
        this never scrapes the wider visible set."""
        for collector in await self._storage.list_collectors():
            if not collector.config.get("_backfill_pending"):
                continue
            if not self._collector_alive(collector.id):
                continue  # not running here yet — leave the flag for a later tick
            identity = await self._storage.get_identity(collector.identity_id)
            if identity is None:
                continue
            cmd = BackfillCommand()
            await self.bus.publish(
                command_subject_for(compute_instance_id(identity.name, collector.kind)),
                cmd.model_dump_json().encode("utf-8"),
                headers={"command-kind": cmd.kind},
            )
            cleared = {k: v for k, v in collector.config.items() if k != "_backfill_pending"}
            await self._storage.update_collector(collector_id=collector.id, config=cleared)
            _log.info("supervisor.backfill_dispatched", collector_id=str(collector.id))

    async def reconcile_collectors(self) -> None:
        """Drive each collector toward its desired_state by spawning/terminating
        the real child process, and report observed_state from actual liveness."""
        now = self._monotonic()
        for collector in await self._storage.list_collectors():
            cid = collector.id
            proc = self._procs.get(cid)
            alive = proc is not None and proc.returncode is None

            # 1. A child we launched has exited. Reap the handle, then decide:
            #    unexpected (operator still wants RUNNING) => CRASHED + cool;
            #    expected (operator stopped it) => settle STOPPED.
            if proc is not None and proc.returncode is not None:
                del self._procs[cid]
                alive = False
                if collector.desired_state is CollectorDesiredState.RUNNING:
                    rc = collector.restart_count + 1
                    self._cooling_until[cid] = now + min(2.0**rc, _MAX_COOLING_S)
                    _log.warning(
                        "supervisor.collector_crashed",
                        collector_id=str(cid),
                        exit_code=proc.returncode,
                        restart_count=rc,
                    )
                    await self._set_observed(
                        collector,
                        CollectorObservedState.CRASHED,
                        restart_count=rc,
                        error_type="process_exit",
                        error_message=f"collector process exited with code {proc.returncode}",
                    )
                    continue

            # 2. Operator wants it stopped/disabled: kill any live child, settle.
            if collector.desired_state in (
                CollectorDesiredState.STOPPED,
                CollectorDesiredState.DISABLED,
            ):
                if alive and proc is not None:
                    proc.terminate()
                    del self._procs[cid]
                self._cooling_until.pop(cid, None)
                await self._set_observed(collector, CollectorObservedState.STOPPED)
                continue

            # 3. Operator wants it running.
            if alive:
                await self._heartbeat(collector)
                continue
            cool = self._cooling_until.get(cid)
            if cool is not None and now < cool:
                await self._set_observed(collector, CollectorObservedState.COOLING)
                continue
            self._cooling_until.pop(cid, None)  # cooldown elapsed (or never set)
            spawned = await self._spawn(collector)
            if spawned is not None:
                self._procs[cid] = spawned
                await self._set_observed(
                    collector,
                    CollectorObservedState.RUNNING,
                    last_heartbeat_at=self._wall_now(),
                )
            else:
                rc = collector.restart_count + 1
                self._cooling_until[cid] = now + min(2.0**rc, _MAX_COOLING_S)
                await self._set_observed(
                    collector,
                    CollectorObservedState.CRASHED,
                    restart_count=rc,
                    error_type="spawn_failed",
                    error_message="spawn failed: missing identity or OS refused the process",
                )

    def _collector_alive(self, collector_id: UUID | None) -> bool:
        """True only if this supervisor is running a live child for that collector
        (running => subscribed to its command channel, so a join command lands)."""
        if collector_id is None:
            return False
        proc = self._procs.get(collector_id)
        return proc is not None and proc.returncode is None

    async def dispatch_approved(self) -> None:
        """Dispatch every candidate ready to join.

        Two shapes share the candidate machinery but diverge on selection:

        * **Operator join-at-will** (no discovery lineage — the candidate has no
          mention rows because it was created by ``ensure_candidate`` from
          /monitored-groups): the operator explicitly chose this group AND a
          collector, so skip the discovery eligibility gate + scout lease and
          dispatch straight to the assigned collector, which joins with its own
          identity. Only dispatched when that collector is a live child of this
          supervisor (else the command would be published to a channel nobody is
          subscribed to and lost). Re-dispatched while the candidate is still
          JOINING so a lost command / collector restart self-heals — the
          ``joining → joined`` finalize is CAS-guarded + idempotent.
        * **Discovery** (born from ``record_candidate_mention``, ≥1 mention): run
          the §4.12.3 eligibility predicate, lease a scout, dispatch to it.
        """
        # Snapshot both lists FIRST so a candidate that transitions APPROVED →
        # JOINING during this call is not then re-found (and double-published) by
        # the JOINING pass. APPROVED = initial dispatch; JOINING = operator
        # re-dispatch of a not-yet-confirmed join (discovery JOINING is left alone).
        approved = await self._storage.list_candidates(
            state=CandidateState.APPROVED, limit=_APPROVED_BATCH
        )
        joining = await self._storage.list_candidates(
            state=CandidateState.JOINING, limit=_APPROVED_BATCH
        )
        for candidate in approved:
            await self._dispatch_candidate(candidate, state=CandidateState.APPROVED)
        for candidate in joining:
            await self._dispatch_candidate(candidate, state=CandidateState.JOINING)

    async def _dispatch_candidate(
        self, candidate: GroupCandidateRow, *, state: CandidateState
    ) -> None:
        if candidate.assigned_collector_id is None:
            return
        inputs = await self._storage.compute_eligibility_inputs(candidate.id)
        if not inputs.mentions:
            # Operator candidate: (re)dispatch only when its collector is alive.
            if self._collector_alive(candidate.assigned_collector_id):
                await self._dispatch_operator_join(candidate)
            return
        # Discovery candidate: only dispatch out of APPROVED.
        if state is not CandidateState.APPROVED:
            return
        verdict = await collector_eligibility(
            candidate.id, candidate.assigned_collector_id, self._storage
        )
        if verdict.result is not CollectorEligibilityResult.OK:
            # Not eligible right now — leave APPROVED for a later tick
            # (transient, e.g. no scout) or operator re-decision (structural).
            _log.info(
                "supervisor.join_skipped",
                candidate_id=str(candidate.id),
                result=verdict.result.value,
                reason=verdict.reason,
            )
            return
        scout = await self._storage.lease_scout(candidate.source_id)
        if scout is None:
            # Lost the scout to a concurrent lease — retry next tick.
            _log.info("supervisor.scout_lease_lost", candidate_id=str(candidate.id))
            return
        # E5.5: pick the cheapest usable access artifact (invite link, etc.);
        # None → the public-identifier path on platform_groupid.
        artifacts = await self._storage.list_group_access_artifacts_for_candidate(candidate.id)
        selected = select_access_artifact(artifacts)
        command = JoinGroupCommand(
            candidate_id=candidate.id,
            platform_groupid=candidate.platform_groupid,
            scout_identity_id=scout.id,
            access_artifact_id=selected.id if selected is not None else None,
        )
        await self._storage.transition_candidate(
            candidate_id=candidate.id,
            to_state=CandidateState.JOINING,
        )
        await self.audit.emit(
            event=AuditSubject.CANDIDATE_JOINING.value,
            subject_kind="candidate",
            subject_id=candidate.id,
            payload={
                "command": command.model_dump(mode="json"),
                "assigned_collector_id": str(candidate.assigned_collector_id),
                "scout_identity_id": str(scout.id),
            },
        )
        await self._publish_join_command(scout, command)

    async def _dispatch_operator_join(self, candidate: GroupCandidateRow) -> None:
        """Dispatch an operator-initiated join to its assigned collector.

        No eligibility gate, no scout lease: the operator's explicit choice IS the
        authorization. The command is routed to the assigned collector's own
        command channel so it joins with its own identity."""
        collector = await self._storage.get_collector(candidate.assigned_collector_id)  # type: ignore[arg-type]
        if collector is None:
            _log.warning("supervisor.operator_join_no_collector", candidate_id=str(candidate.id))
            return
        identity = await self._storage.get_identity(collector.identity_id)
        if identity is None:
            _log.warning("supervisor.operator_join_no_identity", candidate_id=str(candidate.id))
            return
        artifacts = await self._storage.list_group_access_artifacts_for_candidate(candidate.id)
        selected = select_access_artifact(artifacts)
        command = JoinGroupCommand(
            candidate_id=candidate.id,
            platform_groupid=candidate.platform_groupid,
            scout_identity_id=identity.id,
            access_artifact_id=selected.id if selected is not None else None,
        )
        # First dispatch (APPROVED) transitions + audits once; a re-dispatch of a
        # still-JOINING candidate just re-publishes (idempotent recovery).
        if candidate.state is CandidateState.APPROVED:
            await self._storage.transition_candidate(
                candidate_id=candidate.id, to_state=CandidateState.JOINING
            )
            await self.audit.emit(
                event=AuditSubject.CANDIDATE_JOINING.value,
                subject_kind="candidate",
                subject_id=candidate.id,
                payload={
                    "command": command.model_dump(mode="json"),
                    "assigned_collector_id": str(candidate.assigned_collector_id),
                    "operator_initiated": True,
                },
            )
        await self._publish_join_command(identity, command)

    async def _publish_join_command(self, scout: IdentityRow, command: JoinGroupCommand) -> None:
        """Publish the JoinGroupCommand to the scout's command channel (M9.E5).

        Routed by the leased scout's ``instance_id`` so the collector process
        running that identity receives it. The command is a bare pydantic model
        (not a BusEnvelope), so it goes out via raw ``bus.publish`` — the
        ``candidate.joining`` audit row above remains the record of intent.
        """
        source = cast("SourceRow | None", await self._storage.get_source(scout.source_id))
        if source is None:
            _log.warning(
                "supervisor.join_command_unpublished",
                candidate_id=str(command.candidate_id),
                reason="scout source missing",
            )
            return
        scout_instance_id = compute_instance_id(scout.name, source.kind)
        await self.bus.publish(
            command_subject_for(scout_instance_id),
            command.model_dump_json().encode("utf-8"),
            headers={"command-kind": command.kind},
        )


__all__ = ["CollectorSupervisor", "select_access_artifact"]
