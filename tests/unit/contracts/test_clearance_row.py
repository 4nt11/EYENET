"""Shape tests for SystemUserClearanceGrantRow (API_PLAN §4.8 contract).

Wire-only smoke tests — the storage helper layer (M9.1a.2b) covers the
90-day cap and lifecycle behaviour. This file just confirms the Pydantic
row contract round-trips and rejects bogus payloads.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError as PydanticValidationError

from eyenet.contracts.audit_subjects import AuditSubject
from eyenet.contracts.clearance import SystemUserClearanceGrantRow
from eyenet.contracts.enums import ClearanceScope

pytestmark = pytest.mark.contract

_NOW = datetime(2026, 5, 24, tzinfo=UTC)


def _grant(**overrides: object) -> SystemUserClearanceGrantRow:
    defaults: dict[str, object] = {
        "user_id": uuid4(),
        "scope": ClearanceScope.READ_RESTRICTED,
        "granted_by_user_id": uuid4(),
        "reason": "court-defensible justification text",
        "granted_at": _NOW,
        "expires_at": _NOW + timedelta(days=30),
    }
    defaults.update(overrides)
    return SystemUserClearanceGrantRow(**defaults)  # type: ignore[arg-type]


def test_happy_path() -> None:
    g = _grant()
    assert g.scope is ClearanceScope.READ_RESTRICTED


def test_reason_min_length_enforced() -> None:
    with pytest.raises(PydanticValidationError):
        _grant(reason="too short")


@pytest.mark.parametrize("scope", list(ClearanceScope))
def test_every_scope_accepted(scope: ClearanceScope) -> None:
    assert _grant(scope=scope).scope is scope


def test_revocation_triplet_round_trips() -> None:
    g = _grant(
        revoked_at=_NOW + timedelta(days=5),
        revoked_by_user_id=uuid4(),
        revocation_reason="user departed organisation",
    )
    assert g.revoked_at is not None


def test_audit_subjects_registered() -> None:
    """AuditSubject covers every event family API_PLAN §4.8/4.9/4.10 emits."""
    families = {s.value.split(".")[2] for s in AuditSubject}
    assert {"clearance", "reclassify", "case"} <= families
