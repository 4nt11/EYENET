"""Integration tests for the CollectorSupervisor (M9.E3).

DoD coverage:
- desired=running + observed=stopped → supervisor transitions observed to running
- crash recovery: a collector already running is left untouched (resumes from
  persisted observed_state, no spurious transition)
- approved candidate + OK eligibility → joining + scout leased + audit
- no available scout → candidate stays approved (retry)
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from eyenet.bus.memory import MemoryBus
from eyenet.contracts.audit_subjects import AuditSubject
from eyenet.contracts.collector import compute_instance_id
from eyenet.contracts.enums import (
    ArtifactSubjectKind,
    ArtifactValidationState,
    CandidateState,
    CollectorDesiredState,
    CollectorObservedState,
    GroupAccessKind,
    GroupKind,
    IdentityRole,
    IdentityState,
    MentionKind,
    SourceKind,
)
from eyenet.contracts.supervisor import JoinGroupCommand, command_subject_for
from eyenet.services.collector_supervisor import _MAX_COOLING_S, CollectorSupervisor
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

_NOW = datetime(2026, 6, 6, tzinfo=UTC)
_ACTOR = UUID("00000000-0000-0000-0000-0000000000a1")
pytestmark = pytest.mark.integration


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


class _FakeProc:
    """Stand-in for asyncio.subprocess.Process (no real child spawned)."""

    def __init__(self) -> None:
        self.returncode: int | None = None
        self.pid = 4242
        self.terminated = False

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15


class _SpySupervisor(CollectorSupervisor):
    """Supervisor whose _spawn returns a fake process and whose clock is fixed,
    so reconcile's spawn/crash/cooling logic is testable without real children."""

    def __init__(self, *, bus: MemoryBus, storage: BaseRepository) -> None:
        super().__init__(bus=bus, storage=storage)
        self.spawned: list[UUID] = []
        self.spawn_ok = True
        self.clock = 1000.0

    def _monotonic(self) -> float:
        return self.clock

    async def _spawn(self, collector):  # type: ignore[no-untyped-def]
        if not self.spawn_ok:
            return None
        self.spawned.append(collector.id)
        return _FakeProc()


def _supervisor(storage: BaseRepository) -> _SpySupervisor:
    return _SpySupervisor(bus=MemoryBus(), storage=storage)


async def _collector(
    storage: BaseRepository,
    src: UUID,
    name: str,
    *,
    desired: CollectorDesiredState = CollectorDesiredState.STOPPED,
) -> UUID:
    ident = await storage.create_identity(name=f"id_{name}", source_id=src, session_path=f"/{name}")
    row = await storage.create_collector(
        instance_name=f"collector-{name}",
        kind=SourceKind.TELEGRAM,
        source_id=src,
        identity_id=ident.id,
        config={},
        created_at=_NOW,
        created_by_user_id=uuid4(),
    )
    if desired is not CollectorDesiredState.STOPPED:
        await storage.set_collector_desired_state(collector_id=row.id, desired_state=desired)
    return row.id


async def test_reconcile_spawns_and_runs(storage: BaseRepository) -> None:
    src = await storage.upsert_source(
        kind=SourceKind.TELEGRAM, display_name="telegram:s", created_at=_NOW
    )
    coll = await _collector(storage, src, "a", desired=CollectorDesiredState.RUNNING)
    sup = _supervisor(storage)
    await sup.reconcile_collectors()
    row = await storage.get_collector(coll)
    assert row.observed_state is CollectorObservedState.RUNNING
    assert sup.spawned == [coll]  # a child was actually launched
    events = [r.event for r in await storage.all_audit()]
    assert AuditSubject.COLLECTOR_RECONCILED.value in events


async def test_reconcile_steady_state_no_respawn(storage: BaseRepository) -> None:
    src = await storage.upsert_source(
        kind=SourceKind.TELEGRAM, display_name="telegram:s", created_at=_NOW
    )
    await _collector(storage, src, "a", desired=CollectorDesiredState.RUNNING)
    sup = _supervisor(storage)
    await sup.reconcile_collectors()  # spawns once → RUNNING
    before = len(await storage.all_audit())
    await sup.reconcile_collectors()  # live handle exists → no respawn, no audit
    assert len(sup.spawned) == 1
    assert len(await storage.all_audit()) == before


async def test_reconcile_stop_terminates_child(storage: BaseRepository) -> None:
    src = await storage.upsert_source(
        kind=SourceKind.TELEGRAM, display_name="telegram:s", created_at=_NOW
    )
    coll = await _collector(storage, src, "a", desired=CollectorDesiredState.RUNNING)
    sup = _supervisor(storage)
    await sup.reconcile_collectors()  # running
    proc = sup._procs[coll]
    await storage.set_collector_desired_state(
        collector_id=coll, desired_state=CollectorDesiredState.STOPPED
    )
    await sup.reconcile_collectors()
    assert proc.terminated is True
    assert coll not in sup._procs
    row = await storage.get_collector(coll)
    assert row.observed_state is CollectorObservedState.STOPPED


async def test_reconcile_crash_cools_then_respawns(storage: BaseRepository) -> None:
    src = await storage.upsert_source(
        kind=SourceKind.TELEGRAM, display_name="telegram:s", created_at=_NOW
    )
    coll = await _collector(storage, src, "a", desired=CollectorDesiredState.RUNNING)
    sup = _supervisor(storage)
    await sup.reconcile_collectors()  # running
    # Child dies unexpectedly while the operator still wants it running.
    sup._procs[coll].returncode = 1
    await sup.reconcile_collectors()
    row = await storage.get_collector(coll)
    assert row.observed_state is CollectorObservedState.CRASHED
    assert row.restart_count == 1
    assert coll not in sup._procs  # handle reaped

    # Still cooling → no respawn, reported COOLING.
    await sup.reconcile_collectors()
    assert coll not in sup._procs
    assert (await storage.get_collector(coll)).observed_state is CollectorObservedState.COOLING

    # Cooldown elapses → respawn.
    sup.clock += _MAX_COOLING_S + 1
    await sup.reconcile_collectors()
    assert coll in sup._procs
    assert (await storage.get_collector(coll)).observed_state is CollectorObservedState.RUNNING


async def test_spawn_builds_collector_argv(
    storage: BaseRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real _spawn resolves the identity name and launches the collector CLI
    for the collector's source kind (exec monkeypatched — no real child)."""
    import eyenet.services.collector_supervisor as mod

    src = await storage.upsert_source(
        kind=SourceKind.TELEGRAM, display_name="telegram:s", created_at=_NOW
    )
    coll_id = await _collector(storage, src, "a", desired=CollectorDesiredState.RUNNING)
    collector = await storage.get_collector(coll_id)

    captured: dict[str, object] = {}

    async def _fake_exec(*argv: str) -> _FakeProc:
        captured["argv"] = argv
        return _FakeProc()

    # A stale IN_USE claim from a hard-killed prior child must be cleared so the
    # respawn can claim the identity.
    await storage.set_identity_state(
        identity_id=collector.identity_id, state=IdentityState.IN_USE
    )

    monkeypatch.setattr(mod.asyncio, "create_subprocess_exec", _fake_exec)
    sup = CollectorSupervisor(bus=MemoryBus(), storage=storage)
    proc = await sup._spawn(collector)

    assert proc is not None
    argv = captured["argv"]
    assert argv[1:] == ("-m", "eyenet.cli", "collector", "--identity", "id_a", "--type", "telegram")
    # stale claim released
    assert (await storage.get_identity(collector.identity_id)).state is IdentityState.AVAILABLE


async def test_spawn_missing_identity_returns_none(
    storage: BaseRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = await storage.upsert_source(
        kind=SourceKind.TELEGRAM, display_name="telegram:s", created_at=_NOW
    )
    coll_id = await _collector(storage, src, "a", desired=CollectorDesiredState.RUNNING)
    collector = await storage.get_collector(coll_id)

    async def _no_identity(_identity_id: object) -> None:
        return None

    monkeypatch.setattr(storage, "get_identity", _no_identity)
    sup = CollectorSupervisor(bus=MemoryBus(), storage=storage)
    assert await sup._spawn(collector) is None


async def _approved_candidate(storage: BaseRepository, src: UUID, collector_id: UUID) -> UUID:
    root = uuid4()
    cand, _ = await storage.record_candidate_mention(
        source_id=src,
        platform_groupid="@target",
        observed_by_collector_id=collector_id,
        observed_in_group_id=root,
        seed_root_id=root,
        depth_from_root=1,
        mention_evidence_ref="e1",
        mention_kind=MentionKind.USERNAME_MENTION,
        mentioned_at_source=_NOW,
        mentioned_at_ingest=_NOW,
        mentioning_actor_id=_ACTOR,
        kind_hint=GroupKind.CHANNEL,
    )
    await storage.transition_candidate(candidate_id=cand.id, to_state=CandidateState.QUEUED)
    await storage.transition_candidate(
        candidate_id=cand.id, to_state=CandidateState.APPROVED, assigned_collector_id=collector_id
    )
    return cand.id


async def test_dispatch_approved_joins_with_scout(storage: BaseRepository) -> None:
    src = await storage.upsert_source(
        kind=SourceKind.TELEGRAM, display_name="telegram:s", created_at=_NOW
    )
    scout = await storage.create_identity(
        name="scout", source_id=src, session_path="/s", role=IdentityRole.SCOUT
    )
    coll = await _collector(storage, src, "a")
    cand = await _approved_candidate(storage, src, coll)

    await _supervisor(storage).dispatch_approved()

    row = await storage.get_candidate(cand)
    assert row.state is CandidateState.JOINING
    leased = await storage.get_identity(scout.id)
    assert leased.state is IdentityState.IN_USE
    events = [r.event for r in await storage.all_audit()]
    assert AuditSubject.CANDIDATE_JOINING.value in events


async def test_dispatch_no_scout_stays_approved(storage: BaseRepository) -> None:
    src = await storage.upsert_source(
        kind=SourceKind.TELEGRAM, display_name="telegram:s", created_at=_NOW
    )
    coll = await _collector(storage, src, "a")  # no scout identity
    cand = await _approved_candidate(storage, src, coll)
    await _supervisor(storage).dispatch_approved()
    assert (await storage.get_candidate(cand)).state is CandidateState.APPROVED


async def test_dispatch_publishes_join_command_to_scout_channel(storage: BaseRepository) -> None:
    """E5: the supervisor publishes the JoinGroupCommand to the leased scout's
    command channel (keyed by the scout's instance_id), while keeping the
    candidate.joining audit record of intent."""
    src = await storage.upsert_source(
        kind=SourceKind.TELEGRAM, display_name="telegram:s", created_at=_NOW
    )
    await storage.create_identity(
        name="scout", source_id=src, session_path="/s", role=IdentityRole.SCOUT
    )
    coll = await _collector(storage, src, "a")
    await _approved_candidate(storage, src, coll)

    bus = MemoryBus()
    captured: list[tuple[str, bytes, dict[str, str]]] = []

    async def _capture(subject: str, payload: bytes, headers: dict[str, str]) -> None:
        captured.append((subject, payload, headers))

    scout_iid = compute_instance_id("scout", SourceKind.TELEGRAM)
    await bus.subscribe(command_subject_for(scout_iid), _capture)
    await CollectorSupervisor(bus=bus, storage=storage).dispatch_approved()

    assert len(captured) == 1
    subject, _payload, headers = captured[0]
    assert subject == command_subject_for(scout_iid)
    assert headers["command-kind"] == "join_group"


async def test_operator_join_bypasses_eligibility_and_scout(storage: BaseRepository) -> None:
    """A join-at-will candidate (no mention lineage) dispatches straight to its
    assigned collector's own channel — no scout identity required, no seed-root
    eligibility gate (which would otherwise wedge it in APPROVED forever)."""
    src = await storage.upsert_source(
        kind=SourceKind.TELEGRAM, display_name="telegram:s", created_at=_NOW
    )
    coll = await _collector(storage, src, "a")  # identity id_a, role monitor; NO scout exists
    # Operator picks a group directly: ensure_candidate creates it with no mentions.
    cand = await storage.ensure_candidate(
        source_id=src, platform_groupid="@picked", seen_at=_NOW, member_dialog=True
    )
    await storage.transition_candidate(candidate_id=cand.id, to_state=CandidateState.QUEUED)
    await storage.transition_candidate(
        candidate_id=cand.id, to_state=CandidateState.APPROVED, assigned_collector_id=coll
    )

    bus = MemoryBus()
    captured: list[tuple[str, bytes, dict[str, str]]] = []

    async def _capture(subject: str, payload: bytes, headers: dict[str, str]) -> None:
        captured.append((subject, payload, headers))

    coll_iid = compute_instance_id("id_a", SourceKind.TELEGRAM)  # the assigned collector's channel
    await bus.subscribe(command_subject_for(coll_iid), _capture)
    sup = CollectorSupervisor(bus=bus, storage=storage)
    sup._procs[coll] = _FakeProc()  # the assigned collector is a live child
    await sup.dispatch_approved()

    # Dispatched despite no scout + no seed root.
    assert (await storage.get_candidate(cand.id)).state is CandidateState.JOINING
    assert len(captured) == 1
    assert captured[0][0] == command_subject_for(coll_iid)
    assert captured[0][2]["command-kind"] == "join_group"
    cmd = JoinGroupCommand.model_validate_json(captured[0][1])
    assert cmd.candidate_id == cand.id
    assert cmd.scout_identity_id is not None  # dispatched with the collector's own identity


async def test_operator_join_skipped_when_collector_not_alive(storage: BaseRepository) -> None:
    """No live child for the assigned collector → don't dispatch (the command would
    be lost); the candidate stays APPROVED until the collector is running."""
    src = await storage.upsert_source(
        kind=SourceKind.TELEGRAM, display_name="telegram:s", created_at=_NOW
    )
    coll = await _collector(storage, src, "a")
    cand = await storage.ensure_candidate(
        source_id=src, platform_groupid="@picked", seen_at=_NOW
    )
    await storage.transition_candidate(candidate_id=cand.id, to_state=CandidateState.QUEUED)
    await storage.transition_candidate(
        candidate_id=cand.id, to_state=CandidateState.APPROVED, assigned_collector_id=coll
    )
    sup = CollectorSupervisor(bus=MemoryBus(), storage=storage)  # _procs empty → not alive
    await sup.dispatch_approved()
    assert (await storage.get_candidate(cand.id)).state is CandidateState.APPROVED


async def test_operator_join_redispatched_while_joining(storage: BaseRepository) -> None:
    """A still-JOINING operator candidate is re-published (idempotent recovery of a
    lost command) without a second state transition/audit."""
    src = await storage.upsert_source(
        kind=SourceKind.TELEGRAM, display_name="telegram:s", created_at=_NOW
    )
    coll = await _collector(storage, src, "a")
    cand = await storage.ensure_candidate(
        source_id=src, platform_groupid="@picked", seen_at=_NOW
    )
    await storage.transition_candidate(candidate_id=cand.id, to_state=CandidateState.QUEUED)
    await storage.transition_candidate(
        candidate_id=cand.id, to_state=CandidateState.APPROVED, assigned_collector_id=coll
    )
    bus = MemoryBus()
    captured: list[str] = []

    async def _capture(subject: str, payload: bytes, headers: dict[str, str]) -> None:
        captured.append(subject)

    coll_iid = compute_instance_id("id_a", SourceKind.TELEGRAM)
    await bus.subscribe(command_subject_for(coll_iid), _capture)
    sup = CollectorSupervisor(bus=bus, storage=storage)
    sup._procs[coll] = _FakeProc()

    await sup.dispatch_approved()  # APPROVED → JOINING + publish
    assert (await storage.get_candidate(cand.id)).state is CandidateState.JOINING
    audits_after_first = len(await storage.all_audit())

    await sup.dispatch_approved()  # JOINING → re-publish, no new transition/audit
    assert len(captured) == 2  # published twice
    assert len(await storage.all_audit()) == audits_after_first  # no second joining audit

    events = [r.event for r in await storage.all_audit()]
    assert AuditSubject.CANDIDATE_JOINING.value in events


# -- E5.5: access-artifact selection on dispatch -----------------------------


async def _dispatch_and_capture_command(storage: BaseRepository) -> JoinGroupCommand:
    """Run one dispatch tick and return the single published JoinGroupCommand."""
    bus = MemoryBus()
    captured: list[bytes] = []

    async def _capture(subject: str, payload: bytes, headers: dict[str, str]) -> None:
        captured.append(payload)

    scout_iid = compute_instance_id("scout", SourceKind.TELEGRAM)
    await bus.subscribe(command_subject_for(scout_iid), _capture)
    await CollectorSupervisor(bus=bus, storage=storage).dispatch_approved()
    assert len(captured) == 1
    return JoinGroupCommand.model_validate_json(captured[0])


async def _seed_scout_collector_candidate(storage: BaseRepository) -> UUID:
    src = await storage.upsert_source(
        kind=SourceKind.TELEGRAM, display_name="telegram:s", created_at=_NOW
    )
    await storage.create_identity(
        name="scout", source_id=src, session_path="/s", role=IdentityRole.SCOUT
    )
    coll = await _collector(storage, src, "a")
    return await _approved_candidate(storage, src, coll)


async def _add_candidate_artifact(
    storage: BaseRepository,
    candidate_id: UUID,
    *,
    kind: GroupAccessKind,
    value: str,
    validation_state: ArtifactValidationState = ArtifactValidationState.UNVERIFIED,
    requires_admin_approval: bool = False,
) -> UUID:
    art = await storage.add_group_access_artifact(
        subject_kind=ArtifactSubjectKind.CANDIDATE,
        group_id=None,
        candidate_id=candidate_id,
        kind=kind,
        value=value,
        discovered_at_ingest=_NOW,
        validation_state=validation_state,
        requires_admin_approval=requires_admin_approval,
    )
    return art.id


async def test_dispatch_selects_usable_invite_artifact(storage: BaseRepository) -> None:
    cand = await _seed_scout_collector_candidate(storage)
    invite_id = await _add_candidate_artifact(
        storage, cand, kind=GroupAccessKind.INVITE_LINK, value="https://t.me/+abc"
    )
    cmd = await _dispatch_and_capture_command(storage)
    assert cmd.access_artifact_id == invite_id


async def test_dispatch_prefers_cheapest_kind(storage: BaseRepository) -> None:
    cand = await _seed_scout_collector_candidate(storage)
    public_id = await _add_candidate_artifact(
        storage, cand, kind=GroupAccessKind.PUBLIC_IDENTIFIER, value="@target"
    )
    await _add_candidate_artifact(
        storage, cand, kind=GroupAccessKind.INVITE_LINK, value="https://t.me/+abc"
    )
    cmd = await _dispatch_and_capture_command(storage)
    # public_identifier outranks invite_link in the preference order.
    assert cmd.access_artifact_id == public_id


async def test_dispatch_falls_back_to_public_when_no_usable_artifact(
    storage: BaseRepository,
) -> None:
    cand = await _seed_scout_collector_candidate(storage)
    # Expired invite + an admin-approval-gated invite → neither usable.
    await _add_candidate_artifact(
        storage,
        cand,
        kind=GroupAccessKind.INVITE_LINK,
        value="https://t.me/+dead",
        validation_state=ArtifactValidationState.EXPIRED,
    )
    await _add_candidate_artifact(
        storage,
        cand,
        kind=GroupAccessKind.INVITE_LINK,
        value="https://t.me/+gated",
        requires_admin_approval=True,
    )
    cmd = await _dispatch_and_capture_command(storage)
    assert cmd.access_artifact_id is None
