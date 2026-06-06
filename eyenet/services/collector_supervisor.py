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

from eyenet.contracts.audit_subjects import AuditSubject
from eyenet.contracts.enums import (
    CandidateState,
    CollectorDesiredState,
    CollectorObservedState,
)
from eyenet.contracts.supervisor import JoinGroupCommand
from eyenet.service import ServiceBase
from eyenet.services.discovery.eligibility import CollectorEligibilityResult, collector_eligibility
from eyenet.telemetry.logging import get_logger

_log = get_logger()
_APPROVED_BATCH = 1000


class CollectorSupervisor(ServiceBase):
    """Tick-driven collector-state reconciler + approved-join dispatcher (M9.E3)."""

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

    async def reconcile_collectors(self) -> None:
        """Drive each collector's observed_state toward its desired_state."""
        for collector in await self._storage.list_collectors():
            target: CollectorObservedState | None = None
            if (
                collector.desired_state is CollectorDesiredState.RUNNING
                and collector.observed_state is CollectorObservedState.STOPPED
            ):
                target = CollectorObservedState.RUNNING
            elif (
                collector.desired_state
                in (CollectorDesiredState.STOPPED, CollectorDesiredState.DISABLED)
                and collector.observed_state is CollectorObservedState.RUNNING
            ):
                target = CollectorObservedState.STOPPED
            if target is None:
                continue
            await self._storage.record_collector_observed_state(
                collector_id=collector.id,
                observed_state=target,
            )
            await self.audit.emit(
                event=AuditSubject.COLLECTOR_RECONCILED.value,
                subject_kind="collector",
                subject_id=collector.id,
                payload={
                    "from": collector.observed_state.value,
                    "to": target.value,
                    "desired": collector.desired_state.value,
                },
            )

    async def dispatch_approved(self) -> None:
        """Gate + lease + dispatch every approved candidate ready to join."""
        approved = await self._storage.list_candidates(
            state=CandidateState.APPROVED, limit=_APPROVED_BATCH
        )
        for candidate in approved:
            if candidate.assigned_collector_id is None:
                continue
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
                continue
            scout = await self._storage.lease_scout(candidate.source_id)
            if scout is None:
                # Lost the scout to a concurrent lease — retry next tick.
                _log.info("supervisor.scout_lease_lost", candidate_id=str(candidate.id))
                continue
            command = JoinGroupCommand(
                candidate_id=candidate.id,
                platform_groupid=candidate.platform_groupid,
                scout_identity_id=scout.id,
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


__all__ = ["CollectorSupervisor"]
