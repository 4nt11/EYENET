# SPDX-License-Identifier: AGPL-3.0-or-later
"""Direct-call unit tests for the PHASE-5 attachment access/manifest handlers.

The ASGI integration suite (tests/integration/api/test_attachment_access.py)
exercises these through the app, but coverage cannot trace ASGI-routed handler
bodies (the Group-F lesson). These tests invoke the handler COROUTINES directly
with a constructed CurrentUser, an in-memory BaseRepository, a fake Request, and
the request body model — crediting the handler-body coverage. Both handlers'
real branches are covered:

  manifest: happy NORMAL, 404, non-NORMAL 403.
  access:   happy NORMAL (streams + journals + consumes nonce), 404,
            non-NORMAL 403, content-hash mismatch (409), invalid signature
            (401), no-registered-key (401), stale timestamp (401).
"""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi.responses import StreamingResponse

from eyenet.api.deps import AuthError, ConflictError, CurrentUser, ResourceNotFound, ScopeForbidden
from eyenet.api.v1.attachments._access_canonical import compute_access_body_hash
from eyenet.api.v1.attachments.api_access_file import attachments_access
from eyenet.api.v1.attachments.api_get_manifest import attachments_manifest
from eyenet.api.v1.schemas.attachments import FileAccessAcknowledgment
from eyenet.contracts.enums import AttachmentKind, SensitivityTier
from eyenet.contracts.message import AttachmentRow
from eyenet.crypto import build_canonical
from eyenet.models.file_access import FileAccessAcknowledgmentTable, FileAccessJournalTable
from eyenet.storage.repository import BaseRepository
from eyenet.storage.sqlmodel_repo._helpers import safe_session

pytestmark = pytest.mark.unit

_BLOB = b"the quick brown fox" * 32


class _FakeURL:
    def __init__(self, path: str) -> None:
        self.path = path


class _FakeRequest:
    """Minimal stand-in for fastapi.Request — only ``.url.path`` is read."""

    def __init__(self, path: str) -> None:
        self.url = _FakeURL(path)


async def _seed_blob(
    storage: BaseRepository,
    data_dir: Path,
    *,
    tier: SensitivityTier = SensitivityTier.NORMAL,
    payload: bytes = _BLOB,
) -> tuple[UUID, str]:
    sha = hashlib.sha256(payload).hexdigest()
    blob_path = data_dir / f"{sha}.bin"
    blob_path.write_bytes(payload)
    blob_id = await storage.put_attachment(
        AttachmentRow(
            message_id=uuid4(),
            kind=AttachmentKind.DOCUMENT,
            mime="application/octet-stream",
            size_bytes=len(payload),
            sha256=sha,
            storage_uri=str(blob_path),
            classifier_tier=tier,
        )
    )
    return blob_id, sha


async def _register_key(storage: BaseRepository, user_id: UUID) -> Ed25519PrivateKey:
    private = Ed25519PrivateKey.generate()
    raw_pub = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    await storage.record_signing_key(user_id, raw_pub)
    return private


def _signed_body(
    private: Ed25519PrivateKey,
    *,
    blob_id: UUID,
    content_hash: str,
    nonce: UUID,
    signed_at: datetime,
    tamper_sig: bool = False,
) -> FileAccessAcknowledgment:
    url = f"/v1/attachments/{blob_id}/access"
    request_id = "req-" + uuid4().hex
    fields: dict[str, object] = {
        "access_nonce": nonce,
        "expected_content_hash": content_hash,
        "request_id": request_id,
        "signed_at": signed_at,
        "reason": "reviewing the attachment for the case",
        "viewing_context": None,
        "case_refs": [],
    }
    body_hash = compute_access_body_hash(fields)
    canonical = build_canonical(
        "POST", url, request_id, signed_at.isoformat(), body_hash, content_hash
    )
    signature = private.sign(canonical)
    if tamper_sig:
        signature = bytes([signature[0] ^ 0x01]) + signature[1:]
    sig_wire = "ed25519:" + base64.urlsafe_b64encode(signature).decode()
    return FileAccessAcknowledgment(operator_signature=sig_wire, **fields)


async def _journal_count(storage: BaseRepository) -> int:
    from sqlmodel import select

    async with safe_session(storage._audit_session_factory) as session:  # type: ignore[attr-defined]
        result = await session.exec(select(FileAccessJournalTable))
        return len(result.all())


async def _nonce_consumed(storage: BaseRepository, nonce: UUID) -> bool:
    from sqlmodel import select

    async with safe_session(storage._audit_session_factory) as session:  # type: ignore[attr-defined]
        result = await session.exec(
            select(FileAccessAcknowledgmentTable).where(
                FileAccessAcknowledgmentTable.nonce == nonce
            )
        )
        row = result.first()
        return row is not None and row.consumed_at is not None


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path


# --- manifest ---------------------------------------------------------------


async def test_manifest_happy_normal_mints_nonce(
    storage: BaseRepository, data_dir: Path, mkuser: Callable[..., CurrentUser]
) -> None:
    user = mkuser()
    blob_id, sha = await _seed_blob(storage, data_dir)
    result = await attachments_manifest(blob_id, user, storage)
    assert result.content_hash == sha
    assert result.tier is SensitivityTier.NORMAL
    assert result.content_size == len(_BLOB)
    # The minted nonce is a live, unconsumed acknowledgment row.
    assert await _nonce_consumed(storage, result.access_nonce) is False


async def test_manifest_missing_blob_is_404(
    storage: BaseRepository, mkuser: Callable[..., CurrentUser]
) -> None:
    with pytest.raises(ResourceNotFound):
        await attachments_manifest(uuid4(), mkuser(), storage)


@pytest.mark.parametrize("tier", [SensitivityTier.RESTRICTED, SensitivityTier.CLASSIFIED])
async def test_manifest_non_normal_is_403(
    storage: BaseRepository, data_dir: Path, mkuser: Callable[..., CurrentUser], tier
) -> None:
    blob_id, _sha = await _seed_blob(storage, data_dir, tier=tier)
    with pytest.raises(ScopeForbidden):
        await attachments_manifest(blob_id, mkuser(), storage)


# --- access -----------------------------------------------------------------


async def test_access_happy_normal_streams_journals_consumes(
    storage: BaseRepository, data_dir: Path, mkuser: Callable[..., CurrentUser]
) -> None:
    user = mkuser()
    private = await _register_key(storage, user.user_id)
    blob_id, sha = await _seed_blob(storage, data_dir)
    nonce = (await attachments_manifest(blob_id, user, storage)).access_nonce
    body = _signed_body(
        private, blob_id=blob_id, content_hash=sha, nonce=nonce, signed_at=datetime.now(tz=UTC)
    )
    req = _FakeRequest(f"/v1/attachments/{blob_id}/access")
    resp = await attachments_access(blob_id, body, req, user, storage)  # type: ignore[arg-type]
    assert isinstance(resp, StreamingResponse)
    chunks = [chunk async for chunk in resp.body_iterator]
    served = b"".join(c if isinstance(c, bytes) else c.encode() for c in chunks)
    assert served == _BLOB
    assert await _journal_count(storage) == 1
    assert await _nonce_consumed(storage, nonce) is True


async def test_access_missing_blob_is_404(
    storage: BaseRepository, data_dir: Path, mkuser: Callable[..., CurrentUser]
) -> None:
    user = mkuser()
    private = await _register_key(storage, user.user_id)
    body = _signed_body(
        private,
        blob_id=uuid4(),
        content_hash="a" * 64,
        nonce=uuid4(),
        signed_at=datetime.now(tz=UTC),
    )
    req = _FakeRequest("/v1/attachments/x/access")
    with pytest.raises(ResourceNotFound):
        await attachments_access(uuid4(), body, req, user, storage)  # type: ignore[arg-type]


@pytest.mark.parametrize("tier", [SensitivityTier.RESTRICTED, SensitivityTier.CLASSIFIED])
async def test_access_non_normal_is_403(
    storage: BaseRepository, data_dir: Path, mkuser: Callable[..., CurrentUser], tier
) -> None:
    user = mkuser()
    private = await _register_key(storage, user.user_id)
    blob_id, sha = await _seed_blob(storage, data_dir, tier=tier)
    body = _signed_body(
        private, blob_id=blob_id, content_hash=sha, nonce=uuid4(), signed_at=datetime.now(tz=UTC)
    )
    req = _FakeRequest(f"/v1/attachments/{blob_id}/access")
    with pytest.raises(ScopeForbidden):
        await attachments_access(blob_id, body, req, user, storage)  # type: ignore[arg-type]
    assert await _journal_count(storage) == 0


async def test_access_content_hash_mismatch_is_409(
    storage: BaseRepository, data_dir: Path, mkuser: Callable[..., CurrentUser]
) -> None:
    user = mkuser()
    private = await _register_key(storage, user.user_id)
    blob_id, _sha = await _seed_blob(storage, data_dir)
    nonce = (await attachments_manifest(blob_id, user, storage)).access_nonce
    body = _signed_body(
        private, blob_id=blob_id, content_hash="c" * 64, nonce=nonce, signed_at=datetime.now(tz=UTC)
    )
    req = _FakeRequest(f"/v1/attachments/{blob_id}/access")
    with pytest.raises(ConflictError):
        await attachments_access(blob_id, body, req, user, storage)  # type: ignore[arg-type]
    assert await _journal_count(storage) == 0


async def test_access_invalid_signature_is_401(
    storage: BaseRepository, data_dir: Path, mkuser: Callable[..., CurrentUser]
) -> None:
    user = mkuser()
    private = await _register_key(storage, user.user_id)
    blob_id, sha = await _seed_blob(storage, data_dir)
    nonce = (await attachments_manifest(blob_id, user, storage)).access_nonce
    body = _signed_body(
        private,
        blob_id=blob_id,
        content_hash=sha,
        nonce=nonce,
        signed_at=datetime.now(tz=UTC),
        tamper_sig=True,
    )
    req = _FakeRequest(f"/v1/attachments/{blob_id}/access")
    with pytest.raises(AuthError):
        await attachments_access(blob_id, body, req, user, storage)  # type: ignore[arg-type]
    assert await _journal_count(storage) == 0


async def test_access_no_registered_key_is_401(
    storage: BaseRepository, data_dir: Path, mkuser: Callable[..., CurrentUser]
) -> None:
    user = mkuser()  # no key registered for this user
    private = Ed25519PrivateKey.generate()
    blob_id, sha = await _seed_blob(storage, data_dir)
    nonce = (await attachments_manifest(blob_id, user, storage)).access_nonce
    body = _signed_body(
        private, blob_id=blob_id, content_hash=sha, nonce=nonce, signed_at=datetime.now(tz=UTC)
    )
    req = _FakeRequest(f"/v1/attachments/{blob_id}/access")
    with pytest.raises(AuthError):
        await attachments_access(blob_id, body, req, user, storage)  # type: ignore[arg-type]
    assert await _journal_count(storage) == 0


async def test_access_no_retained_bytes_is_404_after_journal(
    storage: BaseRepository, data_dir: Path, mkuser: Callable[..., CurrentUser]
) -> None:
    """§5.5 — a NORMAL row with no storage_uri journals the access then 404s the
    bytes (access IS recorded; the bytes are simply not retained)."""
    user = mkuser()
    private = await _register_key(storage, user.user_id)
    sha = hashlib.sha256(b"never-stored").hexdigest()
    blob_id = await storage.put_attachment(
        AttachmentRow(
            message_id=uuid4(),
            kind=AttachmentKind.DOCUMENT,
            mime="application/octet-stream",
            size_bytes=12,
            sha256=sha,
            storage_uri=None,
            classifier_tier=SensitivityTier.NORMAL,
        )
    )
    nonce = (await attachments_manifest(blob_id, user, storage)).access_nonce
    body = _signed_body(
        private, blob_id=blob_id, content_hash=sha, nonce=nonce, signed_at=datetime.now(tz=UTC)
    )
    req = _FakeRequest(f"/v1/attachments/{blob_id}/access")
    with pytest.raises(ResourceNotFound):
        await attachments_access(blob_id, body, req, user, storage)  # type: ignore[arg-type]
    # Evidence-first: the journal row WAS written even though no bytes flowed.
    assert await _journal_count(storage) == 1
    assert await _nonce_consumed(storage, nonce) is True


def test_decode_operator_signature_rejects_bad_forms() -> None:
    """The defensive decode helper fail-closes (401-class) on every malformed
    wire form — covers branches Pydantic's pattern guard never lets reach the
    handler body."""
    from eyenet.api.v1.attachments.api_access_file import _decode_operator_signature

    with pytest.raises(AuthError):
        _decode_operator_signature("notaprefix:abc")
    with pytest.raises(AuthError):
        _decode_operator_signature("ed25519:!!!not-base64!!!")
    with pytest.raises(AuthError):
        _decode_operator_signature("ed25519:" + base64.urlsafe_b64encode(b"short").decode())


async def test_access_stale_timestamp_is_401(
    storage: BaseRepository, data_dir: Path, mkuser: Callable[..., CurrentUser]
) -> None:
    user = mkuser()
    private = await _register_key(storage, user.user_id)
    blob_id, sha = await _seed_blob(storage, data_dir)
    nonce = (await attachments_manifest(blob_id, user, storage)).access_nonce
    stale = datetime.now(tz=UTC) - timedelta(seconds=3600)
    body = _signed_body(private, blob_id=blob_id, content_hash=sha, nonce=nonce, signed_at=stale)
    req = _FakeRequest(f"/v1/attachments/{blob_id}/access")
    with pytest.raises(AuthError):
        await attachments_access(blob_id, body, req, user, storage)  # type: ignore[arg-type]
    assert await _journal_count(storage) == 0
