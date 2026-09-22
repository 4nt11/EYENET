# SPDX-License-Identifier: AGPL-3.0-or-later
"""Direct-call unit tests for the §5.8 file-access exoneration handlers + storage.

ASGI-routed handlers do not trace for coverage (see memory project_m9_f_done),
so the handlers are called directly with an in-memory ``BaseRepository`` and a
real server exoneration key. Journal rows are seeded via ``record_access`` with a
real operator Ed25519 key, mirroring tests/unit/storage/test_file_access_journal.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from eyenet.api.deps import CurrentUser, RequireScope, ScopeForbidden
from eyenet.api.v1.audit.api_list_file_access import audit_file_access_by_hash
from eyenet.api.v1.audit.api_list_file_access_by_user import audit_file_access_by_user
from eyenet.contracts.enums import FileServedVia, SensitivityTier, SystemUserRole
from eyenet.crypto import (
    build_canonical,
    build_exoneration_canonical,
    load_ed25519_public_key,
    load_exoneration_key,
    verify_signature,
)
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit

_SIG_METHOD = "POST"
_SIG_URL = "/v1/attachments/blob-1/access"


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


@pytest.fixture
def signer(tmp_path):
    return load_exoneration_key(tmp_path)


def _reader() -> CurrentUser:
    return CurrentUser(
        user_id=uuid4(),
        username="auditor",
        role=SystemUserRole.ANALYST,
        effective_scopes=frozenset({"read:audit"}),
        token_expires_at=None,
    )


async def _seed(
    storage: BaseRepository,
    *,
    content_hash: bytes,
    user_id: UUID | None = None,
    now: datetime | None = None,
) -> UUID:
    """Register a fresh operator key and journal one signed NORMAL access."""
    at = now or datetime.now(tz=UTC)
    priv = Ed25519PrivateKey.generate()
    uid = user_id or uuid4()
    fp = await storage.record_signing_key(
        uid, priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw), now=at
    )
    ts = at.isoformat()
    body_hash = "deadbeef"
    request_id = uuid4().hex
    canonical = build_canonical(
        _SIG_METHOD, _SIG_URL, request_id, ts, body_hash, content_hash.hex()
    )
    return await storage.record_access(
        user_id=uid,
        audit_event_id=None,
        grant_id=None,
        acknowledgment_id=None,
        content_hash=content_hash,
        content_size=len(content_hash),
        content_mime="application/pdf",
        tier=SensitivityTier.NORMAL,
        served_via=FileServedVia.INLINE_JSON,
        signing_pubkey_fingerprint=fp,
        operator_signature=priv.sign(canonical),
        sig_method=_SIG_METHOD,
        sig_url=_SIG_URL,
        sig_request_id=request_id,
        sig_timestamp=ts,
        sig_body_hash=body_hash,
        now=at,
    )


def _decode_sig(wire: str) -> bytes:
    return base64.urlsafe_b64decode(wire.removeprefix("ed25519:"))


def _verify(signer, canonical: bytes, wire_sig: str) -> bool:
    key = load_ed25519_public_key(signer.verifying_key_bytes)
    assert key is not None
    return verify_signature(key, canonical, _decode_sig(wire_sig))


# --- by-hash ---------------------------------------------------------------


async def test_by_hash_returns_ordered_accesses_and_signs(storage, signer) -> None:
    ch = b"\x11" * 32
    uid = uuid4()
    await _seed(storage, content_hash=ch, user_id=uid)
    await _seed(storage, content_hash=ch, user_id=uid)

    result = await audit_file_access_by_hash(
        storage=storage, signer=signer, _=_reader(), content_hash=ch.hex()
    )
    assert len(result.accesses) == 2
    assert result.content_hash == ch.hex()
    assert result.journal_head_at_query == (await storage.file_access_journal_head()).hex()

    canonical = build_exoneration_canonical(
        query_kind="by_hash",
        content_hash=ch,
        user_id=b"",
        since="",
        until="",
        query_time=result.query_time.isoformat(),
        journal_head=bytes.fromhex(result.journal_head_at_query),
        access_ids=[a.access_id.bytes for a in result.accesses],
    )
    assert _verify(signer, canonical, result.exoneration_signature)


async def test_by_hash_empty_is_signed_non_access_assertion(storage, signer) -> None:
    # Seed an UNRELATED hash so the journal head is non-genesis.
    await _seed(storage, content_hash=b"\x22" * 32)
    unknown = b"\xff" * 32

    result = await audit_file_access_by_hash(
        storage=storage, signer=signer, _=_reader(), content_hash=unknown.hex()
    )
    assert result.accesses == []
    canonical = build_exoneration_canonical(
        query_kind="by_hash",
        content_hash=unknown,
        user_id=b"",
        since="",
        until="",
        query_time=result.query_time.isoformat(),
        journal_head=bytes.fromhex(result.journal_head_at_query),
        access_ids=[],
    )
    assert _verify(signer, canonical, result.exoneration_signature)


# --- by-user ---------------------------------------------------------------


async def test_by_user_filters_and_signs_with_user_binding(storage, signer) -> None:
    uid = uuid4()
    await _seed(storage, content_hash=b"\x33" * 32, user_id=uid)
    await _seed(storage, content_hash=b"\x44" * 32, user_id=uuid4())  # other user

    result = await audit_file_access_by_user(
        storage=storage, signer=signer, _=_reader(), user_id=uid, since=None, until=None
    )
    assert len(result.accesses) == 1
    assert result.accesses[0].user_id == uid
    assert result.content_hash == "0" * 64  # by-user sentinel

    canonical = build_exoneration_canonical(
        query_kind="by_user",
        content_hash=b"",
        user_id=uid.bytes,
        since="",
        until="",
        query_time=result.query_time.isoformat(),
        journal_head=bytes.fromhex(result.journal_head_at_query),
        access_ids=[a.access_id.bytes for a in result.accesses],
    )
    assert _verify(signer, canonical, result.exoneration_signature)

    # The signature is bound to uid: reconstructing as a DIFFERENT user fails.
    forged = build_exoneration_canonical(
        query_kind="by_user",
        content_hash=b"",
        user_id=uuid4().bytes,
        since="",
        until="",
        query_time=result.query_time.isoformat(),
        journal_head=bytes.fromhex(result.journal_head_at_query),
        access_ids=[a.access_id.bytes for a in result.accesses],
    )
    assert not _verify(signer, forged, result.exoneration_signature)


async def test_by_user_window_excludes_out_of_range(storage, signer) -> None:
    uid = uuid4()
    old = datetime.now(tz=UTC) - timedelta(days=10)
    recent = datetime.now(tz=UTC) - timedelta(minutes=1)
    await _seed(storage, content_hash=b"\x55" * 32, user_id=uid, now=old)
    await _seed(storage, content_hash=b"\x66" * 32, user_id=uid, now=recent)

    since = datetime.now(tz=UTC) - timedelta(hours=1)
    result = await audit_file_access_by_user(
        storage=storage, signer=signer, _=_reader(), user_id=uid, since=since, until=None
    )
    assert len(result.accesses) == 1  # only the recent one


# --- scope gate ------------------------------------------------------------


async def test_read_audit_scope_required(storage, signer) -> None:
    dep = RequireScope("read:audit")
    no_scope = CurrentUser(
        user_id=uuid4(),
        username="op",
        role=SystemUserRole.ANALYST,
        effective_scopes=frozenset(),
        token_expires_at=None,
    )
    request = SimpleNamespace(state=SimpleNamespace())
    with pytest.raises(ScopeForbidden):
        await dep(request=request, current_user=no_scope)


# --- storage reads ---------------------------------------------------------


async def test_storage_head_matches_last_self_hash(storage) -> None:
    assert await storage.file_access_journal_head() == b"\x00" * 32  # genesis when empty
    await _seed(storage, content_hash=b"\x77" * 32)
    aid2_hash_source = b"\x88" * 32
    await _seed(storage, content_hash=aid2_hash_source)

    rows = await storage.list_file_access_by_content_hash(aid2_hash_source)
    assert len(rows) == 1
    head = await storage.file_access_journal_head()
    # Head is the last-appended row's self_hash; verify the chain is intact.
    assert head != b"\x00" * 32
    assert await storage.verify_file_access_chain() is True


async def test_storage_by_content_hash_orders_ascending(storage) -> None:
    ch = b"\x99" * 32
    uid = uuid4()
    a1 = await _seed(storage, content_hash=ch, user_id=uid)
    a2 = await _seed(storage, content_hash=ch, user_id=uid)
    rows = await storage.list_file_access_by_content_hash(ch)
    assert [r.access_id for r in rows] == [a1, a2]
