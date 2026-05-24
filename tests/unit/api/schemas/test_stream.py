"""Shape tests for SSE event payloads."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError as PydanticValidationError

from eyenet.api.v1.schemas import (
    AuditEvent,
    ControlEvent,
    LinkageProposedEvent,
    LinkageState,
    LinkageStateChangedEvent,
    PersonaUpdatedEvent,
    StreamGapEvent,
)

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


def test_linkage_proposed_event_happy(uid: UUID, uid2: UUID, uid3: UUID, now: datetime) -> None:
    evt = LinkageProposedEvent(
        event_id=uid,
        linkage_id=uid,
        actor_a_id=uid2,
        actor_b_id=uid3,
        score=0.8,
        method="stylometry",
        ts=now,
    )
    assert evt.method == "stylometry"


@pytest.mark.parametrize("state", list(LinkageState))
def test_linkage_state_changed_event_every_state(
    uid: UUID, now: datetime, state: LinkageState
) -> None:
    evt = LinkageStateChangedEvent(event_id=uid, linkage_id=uid, state=state, ts=now)
    assert evt.state is state


@pytest.mark.parametrize(
    "change",
    ["member_added", "member_removed", "label_changed", "created"],
)
def test_persona_updated_event_every_change(uid: UUID, now: datetime, change: str) -> None:
    evt = PersonaUpdatedEvent(event_id=uid, persona_id=uid, change=change, ts=now)  # type: ignore[arg-type]
    assert evt.change == change


def test_persona_updated_event_rejects_unknown_change(uid: UUID, now: datetime) -> None:
    with pytest.raises(PydanticValidationError):
        PersonaUpdatedEvent.model_validate(
            {
                "event_id": str(uid),
                "persona_id": str(uid),
                "change": "renamed",
                "ts": now.isoformat(),
            },
        )


def test_audit_event_minimal(uid: UUID, now: datetime) -> None:
    evt = AuditEvent(event_id=uid, subject="eyenet.audit.evidence_access", ts=now)
    assert evt.user_id is None


def test_control_event_with_reason(uid: UUID, now: datetime) -> None:
    evt = ControlEvent(
        event_id=uid,
        subject="eyenet.control.panic",
        user_id=uid,
        reason="incident",
        ts=now,
    )
    assert evt.reason == "incident"


def test_stream_gap_event() -> None:
    gap = StreamGapEvent(oldest_available="01HABC")
    assert gap.oldest_available == "01HABC"


def test_stream_gap_event_required() -> None:
    with pytest.raises(PydanticValidationError):
        StreamGapEvent.model_validate({})
