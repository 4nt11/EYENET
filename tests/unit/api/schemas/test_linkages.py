"""Shape tests for linkage-resource schemas + evidence flattening."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError as PydanticValidationError

from eyenet.api.v1.schemas import (
    LinkageDecisionRequest,
    LinkageDetail,
    LinkageEvidence,
    LinkageState,
    LinkageSummary,
)
from eyenet.models.linkage import LinkageTable

pytestmark = pytest.mark.contract


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 5, 24, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def uid() -> UUID:
    return UUID("01906f00-0000-7000-8000-000000000001")


@pytest.fixture
def uid2() -> UUID:
    return UUID("01906f00-0000-7000-8000-000000000002")


@pytest.fixture
def uid3() -> UUID:
    return UUID("01906f00-0000-7000-8000-000000000003")


@pytest.mark.parametrize("state", list(LinkageState))
def test_linkage_summary_every_state(
    uid: UUID, uid2: UUID, uid3: UUID, now: datetime, state: LinkageState
) -> None:
    summary = LinkageSummary(
        linkage_id=uid,
        actor_a_id=uid2,
        actor_b_id=uid3,
        state=state,
        score=0.8,
        method="m",
        proposed_at=now,
    )
    assert summary.state is state


def test_linkage_summary_required(uid: UUID, uid2: UUID, uid3: UUID, now: datetime) -> None:
    payload = {
        "linkage_id": str(uid),
        "actor_a_id": str(uid2),
        "actor_b_id": str(uid3),
        "state": LinkageState.PROPOSED.value,
        "score": 0.1,
        "method": "m",
        "proposed_at": now.isoformat(),
    }
    for missing in ("linkage_id", "actor_a_id", "state", "score", "method", "proposed_at"):
        broken = dict(payload)
        del broken[missing]
        with pytest.raises(PydanticValidationError):
            LinkageSummary.model_validate(broken)


def test_linkage_summary_from_domain(uid: UUID, uid2: UUID, uid3: UUID, now: datetime) -> None:
    linkage = LinkageTable(
        id=uid,
        actor_a_id=uid2,
        actor_b_id=uid3,
        state=LinkageState.PROPOSED,
        method="m",
        score=0.7,
        evidence={},
        proposed_at=now,
    )
    summary = LinkageSummary.from_domain(linkage)
    assert summary.linkage_id == uid
    assert summary.decided_by is None


def test_linkage_summary_from_domain_with_decided_by(
    uid: UUID, uid2: UUID, uid3: UUID, now: datetime
) -> None:
    linkage = LinkageTable(
        id=uid,
        actor_a_id=uid2,
        actor_b_id=uid3,
        state=LinkageState.CONFIRMED,
        method="m",
        score=0.9,
        evidence={},
        proposed_at=now,
        decided_at=now,
        decided_by="anti",
    )
    decider = UUID("01906f00-0000-7000-8000-0000000000aa")
    summary = LinkageSummary.from_domain(linkage, decided_by_user_id=decider)
    assert summary.decided_by == decider


def test_linkage_detail_evidence_flattening(
    uid: UUID, uid2: UUID, uid3: UUID, now: datetime
) -> None:
    linkage = LinkageTable(
        id=uid,
        actor_a_id=uid2,
        actor_b_id=uid3,
        state=LinkageState.CONFIRMED,
        method="m",
        score=0.9,
        evidence={
            "stylometry": {"score": 0.91, "feature": "trigram"},
            "simhash": {"score": 0.8, "distance": 4},
            "garbage_no_score": {"feature": "n/a"},
            "wrong_type": "not a dict",
        },
        proposed_at=now,
    )
    detail = LinkageDetail.from_domain(linkage)
    comparators = sorted(e.comparator for e in detail.evidence)
    assert comparators == ["simhash", "stylometry"]
    sty = next(e for e in detail.evidence if e.comparator == "stylometry")
    assert sty.score == pytest.approx(0.91)
    assert sty.detail == {"feature": "trigram"}


def test_linkage_evidence_explicit_construction() -> None:
    ev = LinkageEvidence(comparator="x", score=0.5, detail={"k": "v"})
    assert ev.detail == {"k": "v"}


def test_linkage_decision_request_min_reason() -> None:
    with pytest.raises(PydanticValidationError):
        LinkageDecisionRequest(reason="")


def test_linkage_decision_request_rejects_extra() -> None:
    with pytest.raises(PydanticValidationError):
        LinkageDecisionRequest.model_validate({"reason": "r", "rogue": "x"})
