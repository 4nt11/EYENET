# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for the telethon-free E5 join core (eyenet/collectors/telegram/_join.py).

The live telethon issuance in real.py is coverage-omitted; this is where the
join state machine (joined / failed / ban→quarantine) is validated, with no
network and no telethon import.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from eyenet.bus.memory import MemoryBus
from eyenet.bus.publisher import BusEnvelopePublisher
from eyenet.collectors.telegram._join import (
    CollectorJoinHandler,
    JoinOutcome,
    classify_join_error,
)
from eyenet.contracts.enums import (
    CandidateState,
    GroupKind,
    IdentityRole,
    IdentityState,
    JoinedVia,
    MentionKind,
    SourceKind,
)
from eyenet.contracts.supervisor import JoinGroupCommand
from eyenet.services.discovery.scout_graduation import ScoutGraduationService
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 6, 6, tzinfo=UTC)
_ACTOR = UUID("00000000-0000-0000-0000-0000000000a1")


class _FakePool:
    """Duck-typed IdentityPool recording release() calls."""

    def __init__(self) -> None:
        self.released: list[tuple[str, IdentityState]] = []

    async def release(self, name: str, *, new_state: IdentityState) -> None:
        self.released.append((name, new_state))


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


def _handler(storage: BaseRepository, pool: _FakePool, *, identity_name: str = "scout"):
    bus = MemoryBus()
    audit = AuditEmitter(BusEnvelopePublisher(bus), storage, service="test", instance_id="t0")
    return CollectorJoinHandler(
        storage=storage,
        audit=audit,
        pool=pool,  # type: ignore[arg-type]  — duck-typed fake
        scout_graduation=ScoutGraduationService(bus=bus, storage=storage),
        identity_name=identity_name,
    )


async def _source(storage: BaseRepository) -> UUID:
    return await storage.upsert_source(
        kind=SourceKind.TELEGRAM, display_name="telegram:s", created_at=_NOW
    )


async def _collector(storage: BaseRepository, src: UUID) -> UUID:
    ident = await storage.create_identity(name="id_c", source_id=src, session_path="/c")
    row = await storage.create_collector(
        instance_name="collector-c",
        kind=SourceKind.TELEGRAM,
        source_id=src,
        identity_id=ident.id,
        config={},
        created_at=_NOW,
        created_by_user_id=uuid4(),
    )
    return row.id


async def _joining_candidate(storage: BaseRepository, src: UUID, collector_id: UUID) -> UUID:
    cand, _ = await storage.record_candidate_mention(
        source_id=src,
        platform_groupid="@target",
        observed_by_collector_id=collector_id,
        observed_in_group_id=uuid4(),
        seed_root_id=uuid4(),
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
    await storage.transition_candidate(candidate_id=cand.id, to_state=CandidateState.JOINING)
    return cand.id


# -- classifier --------------------------------------------------------------


def test_classify_ban_vs_fail() -> None:
    assert classify_join_error("UserBannedInChannelError") is JoinOutcome.BANNED
    assert classify_join_error("FloodWaitError") is JoinOutcome.FAILED
    assert classify_join_error("InviteHashExpiredError") is JoinOutcome.FAILED
    # unknown errors are NOT treated as bans (we don't burn a scout we don't understand)
    assert classify_join_error("SomeBrandNewTelethonError") is JoinOutcome.FAILED


# -- finalize_joined ---------------------------------------------------------


async def test_finalize_joined_writes_group_membership_and_transition(
    storage: BaseRepository,
) -> None:
    src = await _source(storage)
    coll = await _collector(storage, src)
    cand = await _joining_candidate(storage, src, coll)
    scout_id = uuid4()
    cmd = JoinGroupCommand(
        candidate_id=cand, platform_groupid="@target", scout_identity_id=scout_id
    )

    handler = _handler(storage, _FakePool())
    group_id = await handler.finalize_joined(
        cmd, source_uuid=src, collector_id=coll, kind=GroupKind.CHANNEL, title="Target", now=_NOW
    )

    row = await storage.get_candidate(cand)
    assert row.state is CandidateState.JOINED
    assert row.resulting_group_id == group_id

    memberships = await storage.list_active_memberships(collector_id=coll)
    assert len(memberships) == 1
    assert memberships[0].group_id == group_id
    assert memberships[0].joined_via is JoinedVia.CANDIDATE
    assert memberships[0].joined_via_candidate_id == cand

    events = [r.event for r in await storage.all_audit()]
    assert "eyenet.audit.candidate.joined" in events


# -- fail_candidate ----------------------------------------------------------


async def test_fail_candidate_transitions_and_records_reason(storage: BaseRepository) -> None:
    src = await _source(storage)
    coll = await _collector(storage, src)
    cand = await _joining_candidate(storage, src, coll)
    cmd = JoinGroupCommand(candidate_id=cand, platform_groupid="@target", scout_identity_id=uuid4())

    handler = _handler(storage, _FakePool())
    await handler.fail_candidate(cmd, reason="FloodWaitError: wait 42s")

    row = await storage.get_candidate(cand)
    assert row.state is CandidateState.FAILED
    assert row.rejection_reason == "FloodWaitError: wait 42s"
    events = [r.event for r in await storage.all_audit()]
    assert "eyenet.audit.candidate.failed" in events


# -- quarantine_on_ban -------------------------------------------------------


async def test_quarantine_on_ban_fails_candidate_and_burns_scout(storage: BaseRepository) -> None:
    src = await _source(storage)
    coll = await _collector(storage, src)
    cand = await _joining_candidate(storage, src, coll)
    scout = await storage.create_identity(
        name="scout",
        source_id=src,
        session_path="/s",
        role=IdentityRole.SCOUT,
        state=IdentityState.IN_USE,
    )
    cmd = JoinGroupCommand(
        candidate_id=cand, platform_groupid="@target", scout_identity_id=scout.id
    )

    pool = _FakePool()
    handler = _handler(storage, pool, identity_name="scout")
    await handler.quarantine_on_ban(cmd)

    # candidate failed (never reached joined)
    row = await storage.get_candidate(cand)
    assert row.state is CandidateState.FAILED
    assert row.rejection_reason == "banned_on_join"

    # scout burned + quarantined in the DB
    burned = await storage.get_identity(scout.id)
    assert burned.state is IdentityState.BURNED
    assert burned.role is IdentityRole.QUARANTINE

    # file pool reflects the burn (so restart-recovery can't re-offer it)
    assert pool.released == [("scout", IdentityState.BURNED)]

    events = [r.event for r in await storage.all_audit()]
    assert "eyenet.audit.candidate.failed" in events
    assert "eyenet.audit.identity.burned" in events
