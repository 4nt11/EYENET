"""Schema-level tests for `system_user_clearance_grant` (API_PLAN §4.8).

Covers the dialect-agnostic CHECK constraints: reason length floor,
revocation ordering, revocation triplet symmetry.

The 90-day expiry cap lives in the storage helper, not the schema (date math
has no portable ANSI form across SQLite/Postgres/MySQL — see the comment in
`models/clearance.py`). The helper layer's tests cover that bound.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from eyenet.contracts.enums import ClearanceScope
from eyenet.models.clearance import SystemUserClearanceGrantTable
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository  # noqa: F401

_NOW = datetime(2026, 5, 24, tzinfo=UTC)
_VALID_REASON = "court-defensible justification text"  # 35 chars


@pytest.fixture
def session() -> Session:
    import os

    os.environ.setdefault("EYENET_STORAGE_TYPE", "sqlite")
    storage = get_repository(in_memory=True)
    return Session(storage.sync_engine)


def _grant(**overrides: object) -> SystemUserClearanceGrantTable:
    defaults: dict[str, object] = {
        "user_id": uuid4(),
        "scope": ClearanceScope.READ_RESTRICTED,
        "granted_by_user_id": uuid4(),
        "reason": _VALID_REASON,
        "granted_at": _NOW,
        "expires_at": _NOW + timedelta(days=30),
    }
    defaults.update(overrides)
    return SystemUserClearanceGrantTable(**defaults)  # type: ignore[arg-type]


@pytest.mark.unit
def test_happy_path_30_day_grant(session: Session) -> None:
    session.add(_grant())
    session.commit()


@pytest.mark.unit
def test_long_expiry_accepted_at_schema_layer(session: Session) -> None:
    """Schema does NOT enforce the 90-day cap — the storage helper does.

    Confirms the model layer stays dialect-agnostic: date-math CHECKs would
    couple us to SQLite's `julianday()`. The helper-layer test (when it
    lands) covers the actual 90-day bound.
    """
    session.add(_grant(expires_at=_NOW + timedelta(days=365)))
    session.commit()


@pytest.mark.unit
def test_reason_min_16_chars(session: Session) -> None:
    session.add(_grant(reason="too short"))
    with pytest.raises(IntegrityError):
        session.commit()


@pytest.mark.unit
def test_revocation_before_grant_rejected(session: Session) -> None:
    session.add(
        _grant(
            revoked_at=_NOW - timedelta(days=1),
            revoked_by_user_id=uuid4(),
            revocation_reason="malformed revocation",
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


@pytest.mark.unit
def test_revocation_triplet_partial_rejected(session: Session) -> None:
    """revoked_at set but missing revoked_by_user_id and revocation_reason."""
    session.add(_grant(revoked_at=_NOW + timedelta(days=5)))
    with pytest.raises(IntegrityError):
        session.commit()


@pytest.mark.unit
def test_revocation_triplet_complete_accepted(session: Session) -> None:
    session.add(
        _grant(
            revoked_at=_NOW + timedelta(days=5),
            revoked_by_user_id=uuid4(),
            revocation_reason="user departed organisation",
        )
    )
    session.commit()


@pytest.mark.unit
@pytest.mark.parametrize("scope", list(ClearanceScope))
def test_every_clearance_scope_round_trips(session: Session, scope: ClearanceScope) -> None:
    g = _grant(scope=scope)
    session.add(g)
    session.commit()
    session.refresh(g)
    assert g.scope is scope
