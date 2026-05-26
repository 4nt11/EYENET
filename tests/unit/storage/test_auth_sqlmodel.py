"""SQLite-pinned schema CHECK probes for the M9.A1 auth tables.

Raw INSERTs via the sync engine to verify CHECK constraints fire as
backstops when callers bypass :class:`AuthMixin` (CLAUDE.md §2.3 Rule 2 —
``_sqlite`` filename suffix + env pin).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from eyenet.models.auth import RefreshTokenTable
from eyenet.storage.factory import get_repository

_NOW = datetime(2026, 5, 25, tzinfo=UTC)
_EXP = _NOW + timedelta(days=30)


@pytest.fixture
def session(monkeypatch: pytest.MonkeyPatch) -> Session:
    monkeypatch.setenv("EYENET_STORAGE_TYPE", "sqlite")
    storage = get_repository(in_memory=True)
    return Session(storage.sync_engine)  # type: ignore[attr-defined]


# --- CHECK enforcement ----------------------------------------------


@pytest.mark.unit
def test_replaced_by_without_revoked_at_rejected(session: Session) -> None:
    # replaced_by IS NOT NULL with revoked_at IS NULL must fail the CHECK.
    other = uuid4()
    row = RefreshTokenTable(
        user_id=uuid4(),
        hash="a" * 64,
        issued_at=_NOW,
        expires_at=_EXP,
        revoked_at=None,
        replaced_by=other,  # CHECK violation: replacement implies revocation
    )
    session.add(row)
    with pytest.raises(IntegrityError):
        session.commit()


@pytest.mark.unit
def test_revoked_at_before_issued_at_rejected(session: Session) -> None:
    # revoked_at < issued_at must fail the CHECK.
    row = RefreshTokenTable(
        user_id=uuid4(),
        hash="b" * 64,
        issued_at=_NOW,
        expires_at=_EXP,
        revoked_at=_NOW - timedelta(seconds=1),  # before issued_at
    )
    session.add(row)
    with pytest.raises(IntegrityError):
        session.commit()


@pytest.mark.unit
def test_logout_revoke_without_replacement_accepted(session: Session) -> None:
    # Logout path: revoked_at set, replaced_by NULL — must be accepted.
    row = RefreshTokenTable(
        user_id=uuid4(),
        hash="c" * 64,
        issued_at=_NOW,
        expires_at=_EXP,
        revoked_at=_NOW + timedelta(minutes=5),
        replaced_by=None,
    )
    session.add(row)
    session.commit()  # no IntegrityError


@pytest.mark.unit
def test_hash_unique_collision_rejected(session: Session) -> None:
    # Two tokens with the same hash → UNIQUE violation.
    row_a = RefreshTokenTable(
        user_id=uuid4(),
        hash="d" * 64,
        issued_at=_NOW,
        expires_at=_EXP,
    )
    row_b = RefreshTokenTable(
        user_id=uuid4(),
        hash="d" * 64,  # same hash as row_a
        issued_at=_NOW,
        expires_at=_EXP,
    )
    session.add(row_a)
    session.commit()
    session.add(row_b)
    with pytest.raises(IntegrityError):
        session.commit()
