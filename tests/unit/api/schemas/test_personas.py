"""Shape tests for persona-resource schemas + label-synthesis fallback."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError as PydanticValidationError

from eyenet.api.v1.schemas import (
    PersonaDetail,
    PersonaMember,
    PersonaSummary,
)
from eyenet.models.persona import PersonaMembershipTable, PersonaTable

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


def test_persona_summary_happy(uid: UUID) -> None:
    summary = PersonaSummary(persona_id=uid, label="Cluster A", member_count=5)
    assert summary.member_count == 5


@pytest.mark.parametrize("missing", ["persona_id", "label", "member_count"])
def test_persona_summary_required(missing: str, uid: UUID) -> None:
    payload = {"persona_id": str(uid), "label": "x", "member_count": 1}
    del payload[missing]
    with pytest.raises(PydanticValidationError):
        PersonaSummary.model_validate(payload)


def test_persona_summary_member_count_non_negative(uid: UUID) -> None:
    with pytest.raises(PydanticValidationError):
        PersonaSummary(persona_id=uid, label="x", member_count=-1)


def test_persona_summary_from_domain_uses_label_when_set(uid: UUID, now: datetime) -> None:
    persona = PersonaTable(
        id=uid,
        label="Operator-assigned",
        member_actor_ids=[],
        created_at=now,
        updated_at=now,
    )
    summary = PersonaSummary.from_domain(persona, member_count=3)
    assert summary.label == "Operator-assigned"
    assert summary.member_count == 3


def test_persona_summary_from_domain_synthesizes_when_label_missing(
    uid: UUID,
    now: datetime,
) -> None:
    persona = PersonaTable(
        id=uid,
        label=None,
        member_actor_ids=[],
        created_at=now,
        updated_at=now,
    )
    summary = PersonaSummary.from_domain(persona, member_count=0)
    assert summary.label.startswith("persona-")
    assert uid.hex[:8] in summary.label


def test_persona_detail_extends_summary(uid: UUID, now: datetime) -> None:
    detail = PersonaDetail(
        persona_id=uid,
        label="x",
        member_count=1,
        created_at=now,
        updated_at=now,
    )
    assert detail.created_at == now


def test_persona_detail_from_domain(uid: UUID, now: datetime) -> None:
    persona = PersonaTable(
        id=uid,
        label="x",
        member_actor_ids=[],
        created_at=now,
        updated_at=now,
    )
    detail = PersonaDetail.from_domain(persona, member_count=7)
    assert detail.member_count == 7
    assert detail.created_at == now


def test_persona_member_from_domain(uid: UUID, uid2: UUID, now: datetime) -> None:
    membership = PersonaMembershipTable(
        persona_id=uid,
        actor_id=uid2,
        joined_at=now,
        via_linkage_id=None,
    )
    member = PersonaMember.from_domain(membership)
    assert member.actor_id == uid2
    assert member.since == now
    assert member.via_linkage_id is None
