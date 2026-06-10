# SPDX-License-Identifier: AGPL-3.0-or-later
"""M9.B2 file-access journal — hash-chained, signature-verifying append.

The journal is a SECOND tamper-evident chain in ``audit.db`` mirroring the
audit hash-chain. Every test types the abstract surface (``BaseRepository`` +
``get_repository(in_memory=True)``) per CLAUDE.md §2.3 Rule 2. The one
SQLite-CHECK-constraint probe pins the backend (``_sqlite`` filename suffix +
env pin) — it lives in ``test_file_access_journal_sqlite.py``.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from sqlalchemy import text

from eyenet.contracts.enums import FileServedVia, SensitivityTier
from eyenet.crypto import build_canonical
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository
from eyenet.storage.sqlmodel_repo._helpers import safe_session
from eyenet.storage.sqlmodel_repo.file_access import (
    GENESIS_JOURNAL_HASH,
    FileAccessJournalError,
)

_SIG_METHOD = "POST"
_SIG_URL = "/v1/attachments/blob-1/access"


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


def _new_keypair() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


def _raw_pub(priv: Ed25519PrivateKey) -> bytes:
    return priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


async def _register(
    storage: BaseRepository, priv: Ed25519PrivateKey, now: datetime
) -> tuple[UUID, str]:
    """Register ``priv``'s public key for a fresh user; return (user_id, kid)."""
    user_id = uuid4()
    fp = await storage.record_signing_key(user_id, _raw_pub(priv), now=now)
    return user_id, fp


def _sign(
    priv: Ed25519PrivateKey,
    *,
    request_id: str,
    timestamp: str,
    body_hash: str,
    content_hash: bytes,
) -> bytes:
    """Sign the EYENET-SIG-v1 request canonical with the operator key."""
    canonical = build_canonical(
        _SIG_METHOD, _SIG_URL, request_id, timestamp, body_hash, content_hash.hex()
    )
    return priv.sign(canonical)


async def _record(
    storage: BaseRepository,
    *,
    user_id: UUID,
    fp: str,
    priv: Ed25519PrivateKey,
    content_hash: bytes,
    tier: SensitivityTier = SensitivityTier.NORMAL,
    grant_id: UUID | None = None,
    acknowledgment_id: UUID | None = None,
    request_id: str = "req-1",
    body_hash: str = "deadbeef",
    operator_signature: bytes | None = None,
    now: datetime | None = None,
) -> UUID:
    at = now or datetime.now(tz=UTC)
    ts = at.isoformat()
    sig = operator_signature
    if sig is None:
        sig = _sign(
            priv,
            request_id=request_id,
            timestamp=ts,
            body_hash=body_hash,
            content_hash=content_hash,
        )
    return await storage.record_access(
        user_id=user_id,
        audit_event_id=None,
        grant_id=grant_id,
        acknowledgment_id=acknowledgment_id,
        content_hash=content_hash,
        content_size=len(content_hash),
        content_mime="application/pdf",
        tier=tier,
        served_via=FileServedVia.INLINE_JSON,
        signing_pubkey_fingerprint=fp,
        operator_signature=sig,
        sig_method=_SIG_METHOD,
        sig_url=_SIG_URL,
        sig_request_id=request_id,
        sig_timestamp=ts,
        sig_body_hash=body_hash,
        now=at,
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_record_access_happy_path_persists_and_chains(storage: BaseRepository) -> None:
    """A signed normal-tier access persists and the second row chains to the first."""
    now = datetime.now(tz=UTC)
    priv = _new_keypair()
    user_id, fp = await _register(storage, priv, now)

    aid1 = await _record(
        storage, user_id=user_id, fp=fp, priv=priv, content_hash=b"\x11" * 32, request_id="r1"
    )
    aid2 = await _record(
        storage, user_id=user_id, fp=fp, priv=priv, content_hash=b"\x22" * 32, request_id="r2"
    )
    assert aid1 != aid2
    assert await storage.verify_file_access_chain() is True

    # Genesis: first row links to the all-zero seed; second links to the first.
    async with safe_session(storage._audit_session_factory) as session:  # type: ignore[attr-defined]
        from sqlmodel import select

        from eyenet.models.file_access import FileAccessJournalTable

        rows = (
            await session.exec(select(FileAccessJournalTable).order_by(text("rowid ASC")))
        ).all()
    assert len(rows) == 2
    assert bytes(rows[0].prev_journal_hash) == GENESIS_JOURNAL_HASH
    assert bytes(rows[1].prev_journal_hash) == bytes(rows[0].self_hash)
    assert bytes(rows[0].self_hash) != bytes(rows[1].self_hash)
    # Signature stored on every row (non-repudiation anchor).
    assert rows[0].operator_signature
    assert rows[0].signing_pubkey_fingerprint == fp


@pytest.mark.unit
@pytest.mark.asyncio
async def test_first_access_chains_from_genesis(storage: BaseRepository) -> None:
    now = datetime.now(tz=UTC)
    priv = _new_keypair()
    user_id, fp = await _register(storage, priv, now)
    await _record(storage, user_id=user_id, fp=fp, priv=priv, content_hash=b"\x33" * 32)

    async with safe_session(storage._audit_session_factory) as session:  # type: ignore[attr-defined]
        from sqlmodel import select

        from eyenet.models.file_access import FileAccessJournalTable

        row = (await session.exec(select(FileAccessJournalTable))).first()
    assert row is not None
    assert bytes(row.prev_journal_hash) == GENESIS_JOURNAL_HASH


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tamper_breaks_chain(storage: BaseRepository) -> None:
    """Mutating a stored row's identity field makes verify return False."""
    now = datetime.now(tz=UTC)
    priv = _new_keypair()
    user_id, fp = await _register(storage, priv, now)
    await _record(
        storage, user_id=user_id, fp=fp, priv=priv, content_hash=b"\x44" * 32, request_id="a"
    )
    await _record(
        storage, user_id=user_id, fp=fp, priv=priv, content_hash=b"\x55" * 32, request_id="b"
    )
    assert await storage.verify_file_access_chain() is True

    # Tamper the first row's content_size — self_hash no longer matches.
    async with safe_session(storage._audit_session_factory) as session:  # type: ignore[attr-defined]
        await session.exec(
            text(
                "UPDATE file_access_journal SET content_size = 999999 "
                "WHERE rowid = (SELECT MIN(rowid) FROM file_access_journal)"
            )
        )
        await session.commit()
    assert await storage.verify_file_access_chain() is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_invalid_signature_rejected_no_row(storage: BaseRepository) -> None:
    now = datetime.now(tz=UTC)
    priv = _new_keypair()
    user_id, fp = await _register(storage, priv, now)

    with pytest.raises(FileAccessJournalError):
        await _record(
            storage,
            user_id=user_id,
            fp=fp,
            priv=priv,
            content_hash=b"\x66" * 32,
            operator_signature=b"\x00" * 64,  # garbage signature
        )
    assert await _journal_count(storage) == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_signature_over_wrong_content_hash_rejected(storage: BaseRepository) -> None:
    """A signature valid for a DIFFERENT content_hash must not verify."""
    now = datetime.now(tz=UTC)
    priv = _new_keypair()
    user_id, fp = await _register(storage, priv, now)
    ts = now.isoformat()
    # Sign over content_hash X but submit content_hash Y.
    sig = _sign(priv, request_id="r", timestamp=ts, body_hash="bb", content_hash=b"\xaa" * 32)
    with pytest.raises(FileAccessJournalError):
        await storage.record_access(
            user_id=user_id,
            audit_event_id=None,
            grant_id=None,
            acknowledgment_id=None,
            content_hash=b"\xbb" * 32,
            content_size=32,
            content_mime="application/pdf",
            tier=SensitivityTier.NORMAL,
            served_via=FileServedVia.INLINE_JSON,
            signing_pubkey_fingerprint=fp,
            operator_signature=sig,
            sig_method=_SIG_METHOD,
            sig_url=_SIG_URL,
            sig_request_id="r",
            sig_timestamp=ts,
            sig_body_hash="bb",
            now=now,
        )
    assert await _journal_count(storage) == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_unknown_fingerprint_rejected_no_row(storage: BaseRepository) -> None:
    now = datetime.now(tz=UTC)
    priv = _new_keypair()
    user_id, _fp = await _register(storage, priv, now)
    with pytest.raises(FileAccessJournalError):
        await _record(
            storage,
            user_id=user_id,
            fp="ffffffffffffffff",  # no key with this kid
            priv=priv,
            content_hash=b"\x77" * 32,
        )
    assert await _journal_count(storage) == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_nonnormal_tier_without_grant_or_ack_rejected(storage: BaseRepository) -> None:
    """RESTRICTED access lacking grant_id/acknowledgment_id is fail-closed."""
    now = datetime.now(tz=UTC)
    priv = _new_keypair()
    user_id, fp = await _register(storage, priv, now)
    with pytest.raises(FileAccessJournalError):
        await _record(
            storage,
            user_id=user_id,
            fp=fp,
            priv=priv,
            content_hash=b"\x88" * 32,
            tier=SensitivityTier.RESTRICTED,
            grant_id=None,
            acknowledgment_id=None,
        )
    assert await _journal_count(storage) == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_nonnormal_tier_with_grant_and_nonce_succeeds_and_consumes(
    storage: BaseRepository,
) -> None:
    """RESTRICTED with a live nonce + grant journals; the nonce is then spent."""
    now = datetime.now(tz=UTC)
    priv = _new_keypair()
    user_id, fp = await _register(storage, priv, now)
    content_hash = b"\x99" * 32
    nonce = await storage.record_acknowledgment(user_id, content_hash.hex(), now=now)
    grant_id = uuid4()

    aid = await _record(
        storage,
        user_id=user_id,
        fp=fp,
        priv=priv,
        content_hash=content_hash,
        tier=SensitivityTier.RESTRICTED,
        grant_id=grant_id,
        acknowledgment_id=nonce,
        now=now,
    )
    assert isinstance(aid, UUID)
    assert await storage.verify_file_access_chain() is True

    # The nonce is single-use: a second access reusing it is rejected and the
    # signature-verified-but-nonce-dead access writes NO row.
    with pytest.raises(FileAccessJournalError):
        await _record(
            storage,
            user_id=user_id,
            fp=fp,
            priv=priv,
            content_hash=content_hash,
            tier=SensitivityTier.RESTRICTED,
            grant_id=grant_id,
            acknowledgment_id=nonce,
            request_id="reuse",
            now=now,
        )
    assert await _journal_count(storage) == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_concurrent_appends_stay_linear(storage: BaseRepository) -> None:
    """Two concurrent record_access calls produce a single linear chain.

    The asyncio.Lock + BEGIN IMMEDIATE single-writer serialization must
    prevent a fork (two rows sharing the same prev_journal_hash) or a
    duplicate self_hash.
    """
    now = datetime.now(tz=UTC)
    priv = _new_keypair()
    user_id, fp = await _register(storage, priv, now)

    async def one(i: int) -> UUID:
        return await _record(
            storage,
            user_id=user_id,
            fp=fp,
            priv=priv,
            content_hash=bytes([i]) * 32,
            request_id=f"c{i}",
        )

    await asyncio.gather(*(one(i) for i in range(1, 9)))

    assert await storage.verify_file_access_chain() is True
    async with safe_session(storage._audit_session_factory) as session:  # type: ignore[attr-defined]
        from sqlmodel import select

        from eyenet.models.file_access import FileAccessJournalTable

        rows = (
            await session.exec(select(FileAccessJournalTable).order_by(text("rowid ASC")))
        ).all()
    assert len(rows) == 8
    prevs = [bytes(r.prev_journal_hash) for r in rows]
    selves = [bytes(r.self_hash) for r in rows]
    # No fork: every prev (after genesis) equals the immediately prior self.
    assert prevs[0] == GENESIS_JOURNAL_HASH
    assert prevs[1:] == selves[:-1]
    # No duplicate self_hash.
    assert len(set(selves)) == 8


@pytest.mark.unit
@pytest.mark.asyncio
async def test_failed_append_leaves_nonce_unconsumed_and_retryable(
    storage: BaseRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FIX 1 — consume+append are atomic: a mid-transaction INSERT failure rolls
    BACK the nonce consume, so no row is written AND the client can retry."""
    now = datetime.now(tz=UTC)
    priv = _new_keypair()
    user_id, fp = await _register(storage, priv, now)
    content_hash = b"\xab" * 32
    nonce = await storage.record_acknowledgment(user_id, content_hash.hex(), now=now)
    grant_id = uuid4()

    # Force the journal INSERT (after the nonce would be consumed in the same
    # BEGIN IMMEDIATE transaction) to blow up.
    original = type(storage)._file_access_insert_values  # type: ignore[attr-defined]

    def _boom(*_a: object, **_k: object) -> object:
        raise RuntimeError("forced insert failure mid-transaction")

    monkeypatch.setattr(type(storage), "_file_access_insert_values", staticmethod(_boom))

    with pytest.raises(RuntimeError, match="forced insert failure"):
        await _record(
            storage,
            user_id=user_id,
            fp=fp,
            priv=priv,
            content_hash=content_hash,
            tier=SensitivityTier.RESTRICTED,
            grant_id=grant_id,
            acknowledgment_id=nonce,
            now=now,
        )

    # No row, and the nonce is STILL unconsumed (rolled back).
    assert await _journal_count(storage) == 0

    # Restore the real insert and retry the SAME nonce — must now succeed and
    # consume the nonce exactly once.
    monkeypatch.setattr(type(storage), "_file_access_insert_values", staticmethod(original))
    aid = await _record(
        storage,
        user_id=user_id,
        fp=fp,
        priv=priv,
        content_hash=content_hash,
        tier=SensitivityTier.RESTRICTED,
        grant_id=grant_id,
        acknowledgment_id=nonce,
        request_id="retry",
        now=now,
    )
    assert isinstance(aid, UUID)
    assert await _journal_count(storage) == 1

    # The nonce is now spent — a third attempt with it is rejected (no row).
    with pytest.raises(FileAccessJournalError):
        await _record(
            storage,
            user_id=user_id,
            fp=fp,
            priv=priv,
            content_hash=content_hash,
            tier=SensitivityTier.RESTRICTED,
            grant_id=grant_id,
            acknowledgment_id=nonce,
            request_id="third",
            now=now,
        )
    assert await _journal_count(storage) == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_concurrent_same_nonce_yields_exactly_one_row(storage: BaseRepository) -> None:
    """FIX 1 — concurrent record_access with the SAME nonce: the in-transaction
    consume serializes so exactly one wins (one row, one consumed nonce)."""
    now = datetime.now(tz=UTC)
    priv = _new_keypair()
    user_id, fp = await _register(storage, priv, now)
    content_hash = b"\xcd" * 32
    nonce = await storage.record_acknowledgment(user_id, content_hash.hex(), now=now)
    grant_id = uuid4()

    async def one(rid: str) -> UUID:
        return await _record(
            storage,
            user_id=user_id,
            fp=fp,
            priv=priv,
            content_hash=content_hash,
            tier=SensitivityTier.RESTRICTED,
            grant_id=grant_id,
            acknowledgment_id=nonce,
            request_id=rid,
            now=now,
        )

    results = await asyncio.gather(one("a"), one("b"), return_exceptions=True)
    ok = [r for r in results if isinstance(r, UUID)]
    failed = [r for r in results if isinstance(r, FileAccessJournalError)]
    assert len(ok) == 1
    assert len(failed) == 1
    assert await _journal_count(storage) == 1
    assert await storage.verify_file_access_chain() is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stale_signed_timestamp_rejected_no_row(storage: BaseRepository) -> None:
    """FIX 2 — a signed request whose sig_timestamp is older than the freshness
    window is rejected (closes NORMAL-tier replay). No row is written."""
    now = datetime.now(tz=UTC)
    priv = _new_keypair()
    user_id, fp = await _register(storage, priv, now)
    content_hash = b"\xee" * 32
    stale = now - timedelta(seconds=301)
    ts = stale.isoformat()
    sig = _sign(priv, request_id="r", timestamp=ts, body_hash="bb", content_hash=content_hash)

    with pytest.raises(FileAccessJournalError):
        await storage.record_access(
            user_id=user_id,
            audit_event_id=None,
            grant_id=None,
            acknowledgment_id=None,
            content_hash=content_hash,
            content_size=32,
            content_mime="application/pdf",
            tier=SensitivityTier.NORMAL,
            served_via=FileServedVia.INLINE_JSON,
            signing_pubkey_fingerprint=fp,
            operator_signature=sig,
            sig_method=_SIG_METHOD,
            sig_url=_SIG_URL,
            sig_request_id="r",
            sig_timestamp=ts,
            sig_body_hash="bb",
            now=now,
        )
    assert await _journal_count(storage) == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fresh_signed_timestamp_succeeds(storage: BaseRepository) -> None:
    """FIX 2 — a sig_timestamp inside the window journals normally."""
    now = datetime.now(tz=UTC)
    priv = _new_keypair()
    user_id, fp = await _register(storage, priv, now)
    fresh = now - timedelta(seconds=10)
    content_hash = b"\xef" * 32
    ts = fresh.isoformat()
    sig = _sign(priv, request_id="r", timestamp=ts, body_hash="bb", content_hash=content_hash)
    aid = await storage.record_access(
        user_id=user_id,
        audit_event_id=None,
        grant_id=None,
        acknowledgment_id=None,
        content_hash=content_hash,
        content_size=32,
        content_mime="application/pdf",
        tier=SensitivityTier.NORMAL,
        served_via=FileServedVia.INLINE_JSON,
        signing_pubkey_fingerprint=fp,
        operator_signature=sig,
        sig_method=_SIG_METHOD,
        sig_url=_SIG_URL,
        sig_request_id="r",
        sig_timestamp=ts,
        sig_body_hash="bb",
        now=now,
    )
    assert isinstance(aid, UUID)
    assert await _journal_count(storage) == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_unparseable_signed_timestamp_rejected_no_row(storage: BaseRepository) -> None:
    """FIX 2 — an unparseable sig_timestamp is fail-closed (raise, no row)."""
    now = datetime.now(tz=UTC)
    priv = _new_keypair()
    user_id, fp = await _register(storage, priv, now)
    content_hash = b"\xf0" * 32
    bad_ts = "not-a-timestamp"
    sig = _sign(priv, request_id="r", timestamp=bad_ts, body_hash="bb", content_hash=content_hash)
    with pytest.raises(FileAccessJournalError):
        await storage.record_access(
            user_id=user_id,
            audit_event_id=None,
            grant_id=None,
            acknowledgment_id=None,
            content_hash=content_hash,
            content_size=32,
            content_mime="application/pdf",
            tier=SensitivityTier.NORMAL,
            served_via=FileServedVia.INLINE_JSON,
            signing_pubkey_fingerprint=fp,
            operator_signature=sig,
            sig_method=_SIG_METHOD,
            sig_url=_SIG_URL,
            sig_request_id="r",
            sig_timestamp=bad_ts,
            sig_body_hash="bb",
            now=now,
        )
    assert await _journal_count(storage) == 0


async def _journal_count(storage: BaseRepository) -> int:
    async with safe_session(storage._audit_session_factory) as session:  # type: ignore[attr-defined]
        result = await session.exec(text("SELECT COUNT(*) FROM file_access_journal"))
        return int(result.one()[0])
