"""Shape tests for §4.8 clearance-grant schemas."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError as PydanticValidationError

from eyenet.api.v1.schemas import (
    ClearanceGrantDetail,
    ClearanceGrantRequest,
    ClearanceGrantSummary,
    ClearanceRevokeRequest,
    ClearanceScope,
    CursorPageClearanceGrantSummary,
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


# --- ClearanceGrantRequest --------------------------------------------------


@pytest.mark.parametrize("scope", list(ClearanceScope))
def test_grant_request_every_scope(uid: UUID, now: datetime, scope: ClearanceScope) -> None:
    req = ClearanceGrantRequest(
        user_id=uid,
        scope=scope,
        reason="case=APT-29 peer-reviewed by bob",
        expires_at=now + timedelta(days=30),
    )
    assert req.scope is scope


def test_grant_request_reason_too_short(uid: UUID, now: datetime) -> None:
    with pytest.raises(PydanticValidationError):
        ClearanceGrantRequest(
            user_id=uid,
            scope=ClearanceScope.READ_RESTRICTED,
            reason="ok",
            expires_at=now,
        )


def test_grant_request_rejects_extra(uid: UUID, now: datetime) -> None:
    with pytest.raises(PydanticValidationError):
        ClearanceGrantRequest.model_validate(
            {
                "user_id": str(uid),
                "scope": "read:restricted",
                "reason": "enough characters here ok",
                "expires_at": now.isoformat(),
                "rogue": "x",
            }
        )


def test_grant_request_rejects_unknown_scope(uid: UUID, now: datetime) -> None:
    with pytest.raises(PydanticValidationError):
        ClearanceGrantRequest.model_validate(
            {
                "user_id": str(uid),
                "scope": "read:all",
                "reason": "enough characters here ok",
                "expires_at": now.isoformat(),
            }
        )


# --- ClearanceRevokeRequest -------------------------------------------------


def test_revoke_request_happy() -> None:
    r = ClearanceRevokeRequest(revocation_reason="operator terminated")
    assert r.revocation_reason


def test_revoke_request_requires_reason() -> None:
    with pytest.raises(PydanticValidationError):
        ClearanceRevokeRequest(revocation_reason="")


# --- ClearanceGrantSummary --------------------------------------------------


def test_grant_summary_minimal(uid: UUID, uid2: UUID, now: datetime) -> None:
    s = ClearanceGrantSummary(
        grant_id=uid,
        user_id=uid2,
        scope=ClearanceScope.READ_CLASSIFIED,
        granted_by_user_id=uid,
        granted_at=now,
        expires_at=now + timedelta(days=30),
        active=True,
    )
    assert s.revoked_at is None
    assert s.active is True


# --- ClearanceGrantDetail ---------------------------------------------------


def test_grant_detail_extends_summary(uid: UUID, uid2: UUID, now: datetime) -> None:
    d = ClearanceGrantDetail(
        grant_id=uid,
        user_id=uid2,
        scope=ClearanceScope.READ_RESTRICTED,
        granted_by_user_id=uid,
        granted_at=now,
        expires_at=now + timedelta(days=30),
        active=True,
        reason="case=APT-29 reviewed by legal",
    )
    assert d.reason.startswith("case=")
    assert d.revoked_by_user_id is None
    assert d.parent_grant_id is None


def test_grant_detail_revoked_chain(uid: UUID, uid2: UUID, now: datetime) -> None:
    d = ClearanceGrantDetail(
        grant_id=uid,
        user_id=uid2,
        scope=ClearanceScope.READ_RESTRICTED,
        granted_by_user_id=uid,
        granted_at=now,
        expires_at=now + timedelta(days=30),
        active=False,
        reason="case=APT-29 reviewed by legal",
        revoked_at=now,
        revoked_by_user_id=uid,
        revocation_reason="operator terminated",
        parent_grant_id=uid2,
    )
    assert d.active is False
    assert d.parent_grant_id == uid2


def test_grant_detail_rejects_short_reason(uid: UUID, uid2: UUID, now: datetime) -> None:
    with pytest.raises(PydanticValidationError):
        ClearanceGrantDetail(
            grant_id=uid,
            user_id=uid2,
            scope=ClearanceScope.READ_RESTRICTED,
            granted_by_user_id=uid,
            granted_at=now,
            expires_at=now + timedelta(days=30),
            active=True,
            reason="ok",
        )


# --- CursorPageClearanceGrantSummary ---------------------------------------


def test_cursor_page_empty() -> None:
    page = CursorPageClearanceGrantSummary()
    assert page.items == []


def test_cursor_page_rejects_extra() -> None:
    with pytest.raises(PydanticValidationError):
        CursorPageClearanceGrantSummary.model_validate(
            {
                "items": [],
                "rogue": "x",
            }
        )
