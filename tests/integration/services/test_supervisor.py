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
from eyenet.services.collector_supervisor import CollectorSupervisor
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

_NOW = datetime(2026, 6, 6, tzinfo=UTC)
_ACTOR = UUID("00000000-0000-0000-0000-0000000000a1")
pytestmark = pytest.mark.integration


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


def _supervisor(storage: BaseRepository) -> CollectorSupervisor:
    return CollectorSupervisor(bus=MemoryBus(), storage=storage)


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


async def test_reconcile_starts_running(storage: BaseRepository) -> None:
    src = await storage.upsert_source(
        kind=SourceKind.TELEGRAM, display_name="telegram:s", created_at=_NOW
    )
    coll = await _collector(storage, src, "a", desired=CollectorDesiredState.RUNNING)
    await _supervisor(storage).reconcile_collectors()
    row = await storage.get_collector(coll)
    assert row.observed_state is CollectorObservedState.RUNNING
    events = [r.event for r in await storage.all_audit()]
    assert AuditSubject.COLLECTOR_RECONCILED.value in events


async def test_reconcile_resumes_from_observed_state(storage: BaseRepository) -> None:
    src = await storage.upsert_source(
        kind=SourceKind.TELEGRAM, display_name="telegram:s", created_at=_NOW
    )
    coll = await _collector(storage, src, "a", desired=CollectorDesiredState.RUNNING)
    # already reconciled (crash-recovery: observed persisted as RUNNING)
    await storage.record_collector_observed_state(
        collector_id=coll, observed_state=CollectorObservedState.RUNNING
    )
    before = len(await storage.all_audit())
    await _supervisor(storage).reconcile_collectors()
    # no spurious transition → no new audit row
    assert len(await storage.all_audit()) == before


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
    scout = await storage.create_identity(
        name="scout", source_id=src, session_path="/s", role=IdentityRole.SCOUT
    )
    coll = await _collector(storage, src, "a")
    cand = await _approved_candidate(storage, src, coll)

    bus = MemoryBus()
    captured: list[tuple[str, bytes, dict[str, str]]] = []

    async def _capture(subject: str, payload: bytes, headers: dict[str, str]) -> None:
        captured.append((subject, payload, headers))

    scout_iid = compute_instance_id("scout", SourceKind.TELEGRAM)
    await bus.subscribe(command_subject_for(scout_iid), _capture)
    await CollectorSupervisor(bus=bus, storage=storage).dispatch_approved()

    assert len(captured) == 1
    subject, payload, headers = captured[0]
    assert subject == command_subject_for(scout_iid)
    assert headers["command-kind"] == "join_group"
    cmd = JoinGroupCommand.model_validate_json(payload)
    assert cmd.candidate_id == cand
    assert cmd.scout_identity_id == scout.id

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
