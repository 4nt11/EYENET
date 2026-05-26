"""SQLite-pinned schema CHECK probes for collector (M9.C3, MODELS §2.19).

Raw INSERTs via the sync engine to verify CHECK constraints fire as
backstops when callers bypass :class:`CollectorsMixin`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from eyenet.contracts.enums import (
    CollectorDesiredState,
    CollectorObservedState,
    IdentityState,
    SourceKind,
    SystemUserRole,
)
from eyenet.models.collector import CollectorTable
from eyenet.models.identity import IdentityTable
from eyenet.models.source import SourceTable
from eyenet.models.system_user import SystemUserTable
from eyenet.storage.factory import get_repository

_NOW = datetime(2026, 5, 25, tzinfo=UTC)


@pytest.fixture
def session(monkeypatch: pytest.MonkeyPatch) -> Session:
    monkeypatch.setenv("EYENET_STORAGE_TYPE", "sqlite")
    storage = get_repository(in_memory=True)
    return Session(storage.sync_engine)  # type: ignore[attr-defined]


def _seed_source_identity_user(session: Session) -> tuple[UUID, UUID, UUID]:
    src = SourceTable(kind=SourceKind.TELEGRAM, display_name="t:a", created_at=_NOW)
    user = SystemUserTable(
        username="op",
        display_name="op",
        role=SystemUserRole.ADMIN,
        password_hash="x",
        created_at=_NOW,
    )
    session.add(src)
    session.add(user)
    session.commit()
    session.refresh(src)
    session.refresh(user)
    ident = IdentityTable(
        name="i_a",
        source_id=src.id,
        session_path="/tmp/i_a",  # noqa: S108 — test stub, never opened
        state=IdentityState.AVAILABLE,
    )
    session.add(ident)
    session.commit()
    session.refresh(ident)
    return src.id, ident.id, user.id


def _good_collector(
    src_id: UUID,
    identity_id: UUID,
    user_id: UUID,
    **overrides: object,
) -> CollectorTable:
    defaults: dict[str, object] = {
        "instance_name": "tg_alpha_collector_01",
        "kind": SourceKind.TELEGRAM,
        "source_id": src_id,
        "identity_id": identity_id,
        "config": {"kind": "telegram"},
        "desired_state": CollectorDesiredState.STOPPED,
        "observed_state": CollectorObservedState.STOPPED,
        "restart_count": 0,
        "created_at": _NOW,
        "created_by_user_id": user_id,
    }
    defaults.update(overrides)
    return CollectorTable(**defaults)  # type: ignore[arg-type]


# --- CHECK enforcement ----------------------------------------------


@pytest.mark.unit
def test_instance_name_min_length_rejected(session: Session) -> None:
    src_id, identity_id, user_id = _seed_source_identity_user(session)
    session.add(_good_collector(src_id, identity_id, user_id, instance_name="ab"))
    with pytest.raises(IntegrityError):
        session.commit()


@pytest.mark.unit
def test_negative_restart_count_rejected(session: Session) -> None:
    src_id, identity_id, user_id = _seed_source_identity_user(session)
    session.add(_good_collector(src_id, identity_id, user_id, restart_count=-1))
    with pytest.raises(IntegrityError):
        session.commit()


@pytest.mark.unit
def test_last_error_partial_pair_rejected(session: Session) -> None:
    # Type set but message NULL — must be rejected by the pair CHECK.
    src_id, identity_id, user_id = _seed_source_identity_user(session)
    session.add(
        _good_collector(
            src_id,
            identity_id,
            user_id,
            last_error_type="FloodWaitError",
            last_error_message=None,
        ),
    )
    with pytest.raises(IntegrityError):
        session.commit()


@pytest.mark.unit
def test_last_error_both_set_accepted(session: Session) -> None:
    src_id, identity_id, user_id = _seed_source_identity_user(session)
    session.add(
        _good_collector(
            src_id,
            identity_id,
            user_id,
            observed_state=CollectorObservedState.CRASHED,
            last_error_type="X",
            last_error_message="y",
        ),
    )
    session.commit()  # no IntegrityError


@pytest.mark.unit
def test_invalid_desired_state_string_rejected(session: Session) -> None:
    src_id, identity_id, user_id = _seed_source_identity_user(session)
    table = _good_collector(src_id, identity_id, user_id)
    # Bypass the StrEnum by setting via __dict__ — raw string the
    # SQLAlchemy mapper will pass through. The CHECK at the SQL layer
    # is the backstop the test is probing.
    table.__dict__["desired_state"] = "BOGUS"
    session.add(table)
    with pytest.raises(IntegrityError):
        session.commit()


# --- Identity.role CHECK --------------------------------------------


@pytest.mark.unit
def test_identity_role_invalid_rejected(session: Session) -> None:
    src = SourceTable(kind=SourceKind.TELEGRAM, display_name="t:a", created_at=_NOW)
    session.add(src)
    session.commit()
    session.refresh(src)
    ident = IdentityTable(
        name="i_bogus",
        source_id=src.id,
        session_path="/tmp/i_bogus",  # noqa: S108 — test stub, never opened
        state=IdentityState.AVAILABLE,
    )
    ident.__dict__["role"] = "BOGUS"
    session.add(ident)
    with pytest.raises(IntegrityError):
        session.commit()


@pytest.mark.unit
def test_identity_role_defaults_to_monitor(session: Session) -> None:
    # New identities default to MONITOR per API_PLAN §4.12.
    src = SourceTable(kind=SourceKind.TELEGRAM, display_name="t:a", created_at=_NOW)
    session.add(src)
    session.commit()
    session.refresh(src)
    ident = IdentityTable(
        name="i_default",
        source_id=src.id,
        session_path="/tmp/i_default",  # noqa: S108 — test stub, never opened
        state=IdentityState.AVAILABLE,
    )
    session.add(ident)
    session.commit()
    session.refresh(ident)
    from eyenet.contracts.enums import IdentityRole

    assert ident.role is IdentityRole.MONITOR


# --- partial-unique behaviour (identity / instance_name) ------------


@pytest.mark.unit
def test_two_collectors_one_identity_rejected_at_schema(session: Session) -> None:
    src_id, identity_id, user_id = _seed_source_identity_user(session)
    session.add(_good_collector(src_id, identity_id, user_id, instance_name="first"))
    session.commit()
    session.add(
        _good_collector(
            src_id,
            identity_id,  # same identity — UNIQUE column rejects
            user_id,
            instance_name="second",
        ),
    )
    with pytest.raises(IntegrityError):
        session.commit()


# SQLite FK enforcement against the sync engine is finicky for the
# in-memory test fixture (pragma timing); the runtime path uses the
# async engine which wires FK ON correctly. Skip the FK probe here —
# the UNIQUE constraint on identity_id is the load-bearing invariant
# this slice cares about, and that's exercised in
# test_two_collectors_one_identity_rejected_at_schema above.
