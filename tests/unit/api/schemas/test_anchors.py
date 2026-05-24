"""Shape tests for §5.9 external-anchoring schemas."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError as PydanticValidationError

from eyenet.api.v1.schemas import Anchor, CursorPageAnchor

pytestmark = pytest.mark.contract

_HASH = "0" * 64
_SIG = "ed25519:" + "A" * 88


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 5, 24, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def uid() -> UUID:
    return UUID("01906f00-0000-7000-8000-000000000001")


def test_anchor_happy(uid: UUID, now: datetime) -> None:
    a = Anchor(
        deployment_id=uid,
        anchor_seq=42,
        anchored_at=now,
        audit_head=_HASH,
        journal_head=_HASH,
        signature=_SIG,
    )
    assert a.anchor_seq == 42


def test_anchor_rejects_negative_seq(uid: UUID, now: datetime) -> None:
    with pytest.raises(PydanticValidationError):
        Anchor(
            deployment_id=uid,
            anchor_seq=-1,
            anchored_at=now,
            audit_head=_HASH,
            journal_head=_HASH,
            signature=_SIG,
        )


def test_anchor_rejects_short_hash(uid: UUID, now: datetime) -> None:
    with pytest.raises(PydanticValidationError):
        Anchor(
            deployment_id=uid,
            anchor_seq=0,
            anchored_at=now,
            audit_head="abc",
            journal_head=_HASH,
            signature=_SIG,
        )


def test_anchor_rejects_bad_signature(uid: UUID, now: datetime) -> None:
    with pytest.raises(PydanticValidationError):
        Anchor(
            deployment_id=uid,
            anchor_seq=0,
            anchored_at=now,
            audit_head=_HASH,
            journal_head=_HASH,
            signature="hmac:xxx",
        )


def test_anchor_rejects_extra(uid: UUID, now: datetime) -> None:
    with pytest.raises(PydanticValidationError):
        Anchor.model_validate(
            {
                "deployment_id": str(uid),
                "anchor_seq": 0,
                "anchored_at": now.isoformat(),
                "audit_head": _HASH,
                "journal_head": _HASH,
                "signature": _SIG,
                "rogue": "x",
            }
        )


def test_cursor_page_anchor_empty() -> None:
    page = CursorPageAnchor()
    assert page.items == []
    assert page.next_cursor is None


def test_cursor_page_anchor_with_items(uid: UUID, now: datetime) -> None:
    a = Anchor(
        deployment_id=uid,
        anchor_seq=0,
        anchored_at=now,
        audit_head=_HASH,
        journal_head=_HASH,
        signature=_SIG,
    )
    page = CursorPageAnchor(items=[a], next_cursor="next", estimated_total=10)
    assert page.items[0].deployment_id == uid
    assert page.estimated_total == 10
