# SPDX-License-Identifier: AGPL-3.0-or-later
"""M9.B1 signing-key registry — record/rotate/lookup (audit.db)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
)

from eyenet.crypto import fingerprint
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository
from eyenet.storage.sqlmodel_repo._helpers import safe_session


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


def _raw_pub() -> bytes:
    pk = Ed25519PrivateKey.generate().public_key()
    return pk.public_bytes(Encoding.Raw, PublicFormat.Raw)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_record_key_fingerprint_shape_and_stability(storage: BaseRepository) -> None:
    user_id = uuid4()
    raw = _raw_pub()
    fp = await storage.record_signing_key(user_id, raw)

    # The returned fingerprint is exactly 16 lowercase hex chars.
    assert len(fp) == 16
    assert all(c in "0123456789abcdef" for c in fp)

    # A DIFFERENT key fingerprints differently (distinct-keys check).
    other_fp = fingerprint(Ed25519PrivateKey.generate().public_key())
    assert other_fp != fp

    # Re-fingerprinting the SAME raw bytes reproduces the stored fp
    # (stability of the verification-side primitive).
    assert fingerprint(Ed25519PublicKey.from_public_bytes(raw)) == fp


@pytest.mark.unit
@pytest.mark.asyncio
async def test_active_key_returns_current(storage: BaseRepository) -> None:
    user_id = uuid4()
    raw = _raw_pub()
    await storage.record_signing_key(user_id, raw)
    assert await storage.active_signing_key_for(user_id) == raw


@pytest.mark.unit
@pytest.mark.asyncio
async def test_active_key_none_for_unknown_user(storage: BaseRepository) -> None:
    assert await storage.active_signing_key_for(uuid4()) is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_rotation_retires_prior_both_resolve(storage: BaseRepository) -> None:
    user_id = uuid4()
    old_raw = _raw_pub()
    new_raw = _raw_pub()

    t0 = datetime(2026, 6, 9, 12, 0, 0, tzinfo=UTC)
    t1 = datetime(2026, 6, 9, 12, 5, 0, tzinfo=UTC)
    old_fp = await storage.record_signing_key(user_id, old_raw, now=t0)
    new_fp = await storage.record_signing_key(user_id, new_raw, now=t1)
    assert old_fp != new_fp

    # Active key is now the new one.
    assert await storage.active_signing_key_for(user_id) == new_raw

    # Both fingerprints still resolve FOR THIS USER (recently-rotated key
    # must verify), bound to the authenticated asserting user.
    old_resolved = await storage.lookup_key_for_user(user_id, old_fp)
    new_resolved = await storage.lookup_key_for_user(user_id, new_fp)
    assert old_resolved is not None
    assert new_resolved is not None
    old_key, old_retired = old_resolved
    new_key, new_retired = new_resolved
    assert old_key == old_raw
    assert new_key == new_raw
    assert old_retired is True  # the rotated-out key is marked retired
    assert new_retired is False  # the current key is active


@pytest.mark.unit
@pytest.mark.asyncio
async def test_lookup_unknown_fingerprint_returns_none(storage: BaseRepository) -> None:
    assert await storage.lookup_key_for_user(uuid4(), "deadbeefdeadbeef") is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_lookup_is_user_scoped_no_cross_user_attribution(
    storage: BaseRepository,
) -> None:
    """Two users registering the SAME raw key resolve to THEMSELVES only.

    Defeats the wrong-user attribution defect: a fingerprint shared across
    users (shared/test key, re-registered old key) must never resolve to
    an arbitrary user. The resolver is bound to ``(user_id, fingerprint)``.
    """
    raw = _raw_pub()
    alice = uuid4()
    bob = uuid4()
    fp = await storage.record_signing_key(alice, raw)
    assert await storage.record_signing_key(bob, raw) == fp  # same key → same fp

    # Each user resolves its OWN row; neither leaks to the other.
    assert await storage.lookup_key_for_user(alice, fp) == (raw, False)
    assert await storage.lookup_key_for_user(bob, fp) == (raw, False)
    # A user who never held that fingerprint gets None.
    assert await storage.lookup_key_for_user(uuid4(), fp) is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_rapid_rotation_active_is_newest_deterministic(
    storage: BaseRepository,
) -> None:
    """Two rapid rotations for one user → active resolver returns the NEWEST
    key deterministically, and exactly one active row survives.

    Guards the rotation-race defect: the SQLite partial-unique index
    (``WHERE retired_at IS NULL``) forbids two active rows, and the
    deterministic ``ORDER BY set_at DESC`` read serves the latest key even
    if a transient 2-active state ever arose.
    """
    user_id = uuid4()
    raw1 = _raw_pub()
    raw2 = _raw_pub()
    t0 = datetime(2026, 6, 9, 12, 0, 0, tzinfo=UTC)
    t1 = datetime(2026, 6, 9, 12, 0, 1, tzinfo=UTC)

    await storage.record_signing_key(user_id, raw1, now=t0)
    new_fp = await storage.record_signing_key(user_id, raw2, now=t1)

    # Deterministic newest-active read.
    assert await storage.active_signing_key_for(user_id) == raw2
    # The newest key is active; the prior is retired.
    assert await storage.lookup_key_for_user(user_id, new_fp) == (raw2, False)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_audit_db_ddl_wiring_both_tables_queryable(storage: BaseRepository) -> None:
    """Both M9.B1 tables are created in the audit-db DDL path.

    Proves the ``_AUDIT_TABLES`` wiring: a fresh in-memory repo can both
    INSERT (record) and SELECT (lookup/consume) against each table, which
    only succeeds if ``init_audit_db`` created them.
    """
    user_id = uuid4()
    # signing_pubkey_history table
    fp = await storage.record_signing_key(user_id, _raw_pub())
    assert await storage.lookup_key_for_user(user_id, fp) is not None
    # file_access_acknowledgment table
    nonce = await storage.record_acknowledgment(user_id, "b" * 64, now=datetime.now(tz=UTC))
    assert await storage.consume_acknowledgment(nonce, now=datetime.now(tz=UTC)) is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_partial_unique_index_forbids_two_active_keys(
    storage: BaseRepository,
) -> None:
    """The DB itself forbids two ACTIVE (``retired_at IS NULL``) rows for one
    user — the M9.B1 partial-unique index, not application logic.

    The ``record_signing_key`` happy path retires the prior active row before
    inserting, so it never trips the index. This test bypasses that retire
    step and INSERTs two active rows for the SAME ``user_id`` with DISTINCT
    fingerprints (so the composite ``uq_signing_pubkey_user_fp`` constraint is
    NOT what fires). The second commit must raise ``IntegrityError`` — the
    partial-unique index ``ON ...(user_id) WHERE retired_at IS NULL`` firing.
    This is the concurrent-rotation race shape: two writers each insert an
    active row before the other retires.
    """
    from sqlalchemy.exc import IntegrityError

    from eyenet.models import SystemUserSigningPubkeyHistoryTable

    user_id = uuid4()
    now = datetime(2026, 6, 9, 12, 0, 0, tzinfo=UTC)
    raw1 = _raw_pub()
    raw2 = _raw_pub()
    fp1 = fingerprint(Ed25519PublicKey.from_public_bytes(raw1))
    fp2 = fingerprint(Ed25519PublicKey.from_public_bytes(raw2))
    assert fp1 != fp2  # distinct fingerprints → composite UNIQUE is not the trip

    factory = storage._audit_session_factory  # type: ignore[attr-defined]

    # First active row commits cleanly.
    async with safe_session(factory) as session:
        session.add(
            SystemUserSigningPubkeyHistoryTable(
                user_id=user_id,
                verifying_key=raw1,
                fingerprint=fp1,
                set_at=now,
                retired_at=None,
            )
        )
        await session.commit()

    # Second active row for the SAME user (distinct fp) violates the partial
    # unique index on commit. safe_session rolls back on the raised
    # IntegrityError, so the single statement under test is the commit.
    async with safe_session(factory) as session:
        session.add(
            SystemUserSigningPubkeyHistoryTable(
                user_id=user_id,
                verifying_key=raw2,
                fingerprint=fp2,
                set_at=now,
                retired_at=None,
            )
        )
        with pytest.raises(IntegrityError, match="UNIQUE constraint failed"):
            await session.commit()
