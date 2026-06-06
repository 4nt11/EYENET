"""Integration tests for the scout graduation pipeline (M9.E4).

DoD coverage:
- scout with window+ continuous membership graduates (role→monitor, audit)
- a fresh scout (inside the window) does NOT graduate
- a burned scout is quarantined and its joined candidate parked
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from eyenet.bus.memory import MemoryBus
from eyenet.contracts.audit_subjects import AuditSubject
from eyenet.contracts.enums import (
    CandidateState,
    GroupKind,
    IdentityRole,
    IdentityState,
    JoinedVia,
    MentionKind,
    SourceKind,
)
from eyenet.services.discovery.scout_graduation import ScoutGraduationService
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

_NOW = datetime(2026, 6, 6, tzinfo=UTC)
_ACTOR = UUID("00000000-0000-0000-0000-0000000000a1")
pytestmark = pytest.mark.integration


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


def _svc(storage: BaseRepository) -> ScoutGraduationService:
    return ScoutGraduationService(bus=MemoryBus(), storage=storage, observation_window_days=7)


async def _scout_in_group(storage: BaseRepository, *, joined_at: datetime) -> tuple[UUID, UUID]:
    """Seed a SCOUT identity whose collector has an active membership.
    Returns (identity_id, group_id)."""
    src = await storage.upsert_source(
        kind=SourceKind.TELEGRAM, display_name="telegram:s", created_at=_NOW
    )
    scout = await storage.create_identity(
        name="scout",
        source_id=src,
        session_path="/s",
        role=IdentityRole.SCOUT,
        state=IdentityState.IN_USE,
    )
    coll = await storage.create_collector(
        instance_name="collector-a",
        kind=SourceKind.TELEGRAM,
        source_id=src,
        identity_id=scout.id,
        config={},
        created_at=_NOW,
        created_by_user_id=uuid4(),
    )
    group = uuid4()
    await storage.open_membership(
        collector_id=coll.id, group_id=group, joined_at=joined_at, joined_via=JoinedVia.SEED
    )
    return scout.id, group


async def test_clean_scout_graduates(storage: BaseRepository) -> None:
    scout_id, _ = await _scout_in_group(storage, joined_at=_NOW - timedelta(days=8))
    n = await _svc(storage).graduate_due(_NOW)
    assert n == 1
    row = await storage.get_identity(scout_id)
    assert row.role is IdentityRole.MONITOR
    assert row.graduated_at == _NOW
    events = [r.event for r in await storage.all_audit()]
    assert AuditSubject.IDENTITY_GRADUATED.value in events


async def test_fresh_scout_does_not_graduate(storage: BaseRepository) -> None:
    scout_id, _ = await _scout_in_group(storage, joined_at=_NOW - timedelta(days=2))
    n = await _svc(storage).graduate_due(_NOW)
    assert n == 0
    assert (await storage.get_identity(scout_id)).role is IdentityRole.SCOUT


async def test_burned_scout_quarantined_and_candidate_parked(storage: BaseRepository) -> None:
    src = await storage.upsert_source(
        kind=SourceKind.TELEGRAM, display_name="telegram:s", created_at=_NOW
    )
    scout = await storage.create_identity(
        name="scout",
        source_id=src,
        session_path="/s",
        role=IdentityRole.SCOUT,
        state=IdentityState.IN_USE,
    )
    # a candidate that reached JOINED (the scout's join)
    cand, _ = await storage.record_candidate_mention(
        source_id=src,
        platform_groupid="@t",
        observed_by_collector_id=uuid4(),
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
    for to in (
        CandidateState.QUEUED,
        CandidateState.APPROVED,
        CandidateState.JOINING,
        CandidateState.JOINED,
    ):
        await storage.transition_candidate(
            candidate_id=cand.id, to_state=to, resulting_group_id=uuid4()
        )

    await _svc(storage).quarantine_scout(
        identity_id=scout.id, reason="banned by platform", candidate_id=cand.id
    )

    burned = await storage.get_identity(scout.id)
    assert burned.state is IdentityState.BURNED
    assert burned.role is IdentityRole.QUARANTINE
    assert (await storage.get_candidate(cand.id)).state is CandidateState.PARKED
    events = [r.event for r in await storage.all_audit()]
    assert AuditSubject.IDENTITY_BURNED.value in events
