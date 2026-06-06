# SPDX-License-Identifier: AGPL-3.0-or-later
"""Direct-call unit tests for the D3 Candidate triage handlers (M9.D3).

Bypasses ASGI routing (coverage can't trace it). The §4.12.3 eligibility
predicate is real (M9.E3) and surfaced on GET; approve itself still does NOT
gate on it (only existence + legal transition) — the supervisor gates at
dispatch.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.exceptions import RequestValidationError

from eyenet.api.deps import ConflictError, CurrentUser, ResourceNotFound
from eyenet.api.deps_paging import CursorParams
from eyenet.api.v1.candidates.api_approve_candidate import candidates_approve
from eyenet.api.v1.candidates.api_get_candidate import candidates_get
from eyenet.api.v1.candidates.api_list_candidates import candidates_list
from eyenet.api.v1.candidates.api_park_candidate import candidates_park
from eyenet.api.v1.candidates.api_reject_candidate import candidates_reject
from eyenet.api.v1.candidates.api_retry_candidate import candidates_retry
from eyenet.api.v1.schemas.candidates import (
    ApproveCandidateRequest,
    ParkCandidateRequest,
    RejectCandidateRequest,
)
from eyenet.bus.memory import MemoryBus
from eyenet.bus.publisher import BusEnvelopePublisher
from eyenet.contracts.enums import (
    CandidateState,
    IdentityState,
    MentionKind,
    SourceKind,
)
from eyenet.models.identity import IdentityTable
from eyenet.services.discovery.eligibility import CollectorEligibilityResult
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 5, 26, tzinfo=UTC)
_FAKE_COLLECTOR = UUID("00000000-0000-0000-0000-0000000000c0")
_FAKE_ACTOR = UUID("00000000-0000-0000-0000-0000000000a0")


@pytest.fixture
def audit(storage: BaseRepository) -> AuditEmitter:
    return AuditEmitter(
        BusEnvelopePublisher(MemoryBus()), storage, service="test", instance_id="t0"
    )


async def _source(storage: BaseRepository) -> UUID:
    return await storage.upsert_source(
        kind=SourceKind.TELEGRAM, display_name="telegram:cand", created_at=_NOW
    )


async def _real_collector(storage: BaseRepository, source_id: UUID) -> UUID:
    async with storage.session() as session:
        ident = IdentityTable(
            name="id_cand",
            source_id=source_id,
            session_path="/tmp/id_cand.session",  # noqa: S108 — test stub
            state=IdentityState.AVAILABLE,
        )
        session.add(ident)
        await session.commit()
        await session.refresh(ident)
    row = await storage.create_collector(
        instance_name="collector_cand",
        kind=SourceKind.TELEGRAM,
        source_id=source_id,
        identity_id=ident.id,
        config={"kind": "telegram"},
        created_at=_NOW,
        created_by_user_id=uuid4(),
    )
    return row.id


async def _candidate(
    storage: BaseRepository, source_id: UUID, *, platform_groupid: str = "g1"
) -> UUID:
    candidate, _ = await storage.record_candidate_mention(
        source_id=source_id,
        platform_groupid=platform_groupid,
        observed_by_collector_id=_FAKE_COLLECTOR,
        observed_in_group_id=uuid4(),
        seed_root_id=None,
        depth_from_root=1,
        mention_evidence_ref=f"telegram:{platform_groupid}:1",
        mention_kind=MentionKind.USERNAME_MENTION,
        mentioned_at_source=_NOW,
        mentioned_at_ingest=_NOW,
        mentioning_actor_id=_FAKE_ACTOR,
    )
    return candidate.id


def _page(limit: int = 50, *, include_total: bool = False) -> CursorParams:
    return CursorParams(offset=0, limit=limit, include_total=include_total)


# --- list + detail --------------------------------------------------------


async def test_list_candidates_filters(
    storage: BaseRepository, mkuser: Callable[..., CurrentUser]
) -> None:
    src = await _source(storage)
    c1 = await _candidate(storage, src, platform_groupid="g1")
    await _candidate(storage, src, platform_groupid="g2")
    await storage.transition_candidate(candidate_id=c1, to_state=CandidateState.QUEUED)

    page = await candidates_list(
        mkuser("read:candidates"), storage, _page(include_total=True), None, None, None
    )
    assert len(page.items) == 2
    assert page.estimated_total == 2

    queued = await candidates_list(
        mkuser("read:candidates"), storage, _page(), CandidateState.QUEUED, None, None
    )
    assert [c.candidate_id for c in queued.items] == [c1]


async def test_get_candidate_detail_eligibility(
    storage: BaseRepository, mkuser: Callable[..., CurrentUser]
) -> None:
    src = await _source(storage)
    coll = await _real_collector(storage, src)
    cid = await _candidate(storage, src)
    detail = await candidates_get(cid, mkuser("read:candidates"), storage)
    assert detail.candidate_id == cid
    assert len(detail.mentions) == 1
    # the real §4.12.3 predicate evaluates the fleet — one collector, and the
    # mention carries no seed root the collector reaches → NO_REACHABLE_ROOT.
    assert len(detail.eligibility_per_collector) == 1
    assert detail.eligibility_per_collector[0].collector_id == coll
    assert (
        detail.eligibility_per_collector[0].result is CollectorEligibilityResult.NO_REACHABLE_ROOT
    )


async def test_get_unknown_candidate_404(
    storage: BaseRepository, mkuser: Callable[..., CurrentUser]
) -> None:
    with pytest.raises(ResourceNotFound):
        await candidates_get(uuid4(), mkuser("read:candidates"), storage)


# --- approve --------------------------------------------------------------


async def test_approve_queued_candidate(
    storage: BaseRepository, audit: AuditEmitter, mkuser: Callable[..., CurrentUser]
) -> None:
    src = await _source(storage)
    cid = await _candidate(storage, src)
    await storage.transition_candidate(candidate_id=cid, to_state=CandidateState.QUEUED)
    collector_id = await _real_collector(storage, src)

    detail = await candidates_approve(
        cid,
        ApproveCandidateRequest(assigned_collector_id=collector_id),
        mkuser("write:candidates"),
        storage,
        audit,
    )
    assert detail.state is CandidateState.APPROVED
    assert detail.assigned_collector_id == collector_id


async def test_approve_unknown_collector_422(
    storage: BaseRepository, audit: AuditEmitter, mkuser: Callable[..., CurrentUser]
) -> None:
    src = await _source(storage)
    cid = await _candidate(storage, src)
    await storage.transition_candidate(candidate_id=cid, to_state=CandidateState.QUEUED)
    with pytest.raises(RequestValidationError):
        await candidates_approve(
            cid,
            ApproveCandidateRequest(assigned_collector_id=uuid4()),
            mkuser("write:candidates"),
            storage,
            audit,
        )


async def test_approve_illegal_state_409(
    storage: BaseRepository, audit: AuditEmitter, mkuser: Callable[..., CurrentUser]
) -> None:
    src = await _source(storage)
    cid = await _candidate(storage, src)  # DISCOVERED, not QUEUED
    collector_id = await _real_collector(storage, src)
    # DISCOVERED → APPROVED is illegal; the collector exists so we reach the
    # transition. (Eligibility is NOT what blocks this — it's the state machine.)
    with pytest.raises(ConflictError, match="illegal candidate transition"):
        await candidates_approve(
            cid,
            ApproveCandidateRequest(assigned_collector_id=collector_id),
            mkuser("write:candidates"),
            storage,
            audit,
        )


# --- reject / park / retry ------------------------------------------------


async def test_reject_candidate(
    storage: BaseRepository, audit: AuditEmitter, mkuser: Callable[..., CurrentUser]
) -> None:
    src = await _source(storage)
    cid = await _candidate(storage, src)
    await storage.transition_candidate(candidate_id=cid, to_state=CandidateState.QUEUED)
    detail = await candidates_reject(
        cid,
        RejectCandidateRequest(reason="spam channel, not actor-relevant"),
        mkuser("write:candidates"),
        storage,
        audit,
    )
    assert detail.state is CandidateState.REJECTED
    assert detail.rejection_reason == "spam channel, not actor-relevant"


async def test_park_joined_candidate(
    storage: BaseRepository, audit: AuditEmitter, mkuser: Callable[..., CurrentUser]
) -> None:
    src = await _source(storage)
    cid = await _candidate(storage, src)
    collector_id = await _real_collector(storage, src)
    # Drive DISCOVERED → QUEUED → APPROVED → JOINING → JOINED.
    await storage.transition_candidate(candidate_id=cid, to_state=CandidateState.QUEUED)
    await storage.transition_candidate(
        candidate_id=cid, to_state=CandidateState.APPROVED, assigned_collector_id=collector_id
    )
    await storage.transition_candidate(candidate_id=cid, to_state=CandidateState.JOINING)
    await storage.transition_candidate(candidate_id=cid, to_state=CandidateState.JOINED)

    detail = await candidates_park(
        cid,
        ParkCandidateRequest(reason="operator left the group"),
        mkuser("write:candidates"),
        storage,
        audit,
    )
    assert detail.state is CandidateState.PARKED


async def test_retry_failed_candidate(
    storage: BaseRepository, audit: AuditEmitter, mkuser: Callable[..., CurrentUser]
) -> None:
    src = await _source(storage)
    cid = await _candidate(storage, src)
    collector_id = await _real_collector(storage, src)
    await storage.transition_candidate(candidate_id=cid, to_state=CandidateState.QUEUED)
    await storage.transition_candidate(
        candidate_id=cid, to_state=CandidateState.APPROVED, assigned_collector_id=collector_id
    )
    await storage.transition_candidate(candidate_id=cid, to_state=CandidateState.JOINING)
    await storage.transition_candidate(candidate_id=cid, to_state=CandidateState.FAILED)

    detail = await candidates_retry(cid, mkuser("admin:candidates"), storage, audit)
    assert detail.state is CandidateState.QUEUED


async def test_retry_unknown_404(
    storage: BaseRepository, audit: AuditEmitter, mkuser: Callable[..., CurrentUser]
) -> None:
    with pytest.raises(ResourceNotFound):
        await candidates_retry(uuid4(), mkuser("admin:candidates"), storage, audit)
