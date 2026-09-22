# SPDX-License-Identifier: AGPL-3.0-or-later
"""Direct-call unit tests for the M10 document access/manifest handlers.

Mirrors tests/unit/api/v1/attachments/test_access_handlers.py exactly: the ASGI
integration layer exercises the routing, but coverage cannot trace ASGI-routed
handler bodies (the Group-F lesson). These tests invoke the handler COROUTINES
directly with a constructed CurrentUser, an in-memory BaseRepository, a fake
Request, and the request body model, crediting the handler-body coverage.

  manifest: happy NORMAL (mints nonce), 404, CLASSIFIED-without-scope 403,
            CLASSIFIED-with-scope 200.
  access:   happy NORMAL (streams + journals + defang headers), 409 hash
            mismatch, 401 no-registered-key, CLASSIFIED-with-grant (journal row
            carries grant_id), 404 missing doc.
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
from eyenet.api.v1.documents.api_access_document import documents_access
from eyenet.api.v1.documents.api_get_document_manifest import documents_manifest
from eyenet.api.v1.schemas.attachments import FileAccessAcknowledgment
from eyenet.contracts.document import DocumentRow
from eyenet.contracts.enums import ClearanceScope, SensitivityTier
from eyenet.crypto import build_canonical
from eyenet.models.file_access import FileAccessJournalTable
from eyenet.storage.repository import BaseRepository
from eyenet.storage.sqlmodel_repo._helpers import safe_session

pytestmark = pytest.mark.unit

_BLOB = b"the quick brown fox jumps over the lazy dog" * 16


class _FakeURL:
    def __init__(self, path: str) -> None:
        self.path = path


class _FakeRequest:
    """Minimal stand-in for fastapi.Request — only ``.url.path`` is read."""

    def __init__(self, path: str) -> None:
        self.url = _FakeURL(path)


async def _seed_document(
    storage: BaseRepository,
    data_dir: Path,
    *,
    tier: SensitivityTier = SensitivityTier.NORMAL,
    payload: bytes = _BLOB,
    with_bytes: bool = True,
) -> tuple[UUID, str]:
    sha = hashlib.sha256(payload).hexdigest()
    storage_uri: str | None = None
    if with_bytes:
        blob_path = data_dir / f"{sha}.bin"
        blob_path.write_bytes(payload)
        storage_uri = str(blob_path)
    now = datetime.now(tz=UTC)
    doc_id = await storage.put_document(
        DocumentRow(
            sha256=sha,
            mime="application/pdf",
            size_bytes=len(payload),
            filename="evidence report.pdf",
            storage_uri=storage_uri,
            uploaded_at=now,
            ingested_at=now,
            classifier_tier=tier,
        )
    )
    return doc_id, sha


async def _register_key(storage: BaseRepository, user_id: UUID) -> Ed25519PrivateKey:
    private = Ed25519PrivateKey.generate()
    raw_pub = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    await storage.record_signing_key(user_id, raw_pub)
    return private


def _signed_body(
    private: Ed25519PrivateKey,
    *,
    document_id: UUID,
    content_hash: str,
    nonce: UUID,
    signed_at: datetime,
) -> FileAccessAcknowledgment:
    url = f"/v1/documents/{document_id}/access"
    request_id = "req-" + uuid4().hex
    fields: dict[str, object] = {
        "access_nonce": nonce,
        "expected_content_hash": content_hash,
        "request_id": request_id,
        "signed_at": signed_at,
        "reason": "reviewing the document for the case",
        "viewing_context": None,
        "case_refs": [],
    }
    body_hash = compute_access_body_hash(fields)
    canonical = build_canonical(
        "POST", url, request_id, signed_at.isoformat(), body_hash, content_hash
    )
    signature = private.sign(canonical)
    sig_wire = "ed25519:" + base64.urlsafe_b64encode(signature).decode()
    return FileAccessAcknowledgment(operator_signature=sig_wire, **fields)


async def _journal_rows(storage: BaseRepository) -> list[FileAccessJournalTable]:
    from sqlmodel import select

    async with safe_session(storage._audit_session_factory) as session:  # type: ignore[attr-defined]
        result = await session.exec(select(FileAccessJournalTable))
        return list(result.all())


async def _grant_read_classified(storage: BaseRepository, user_id: UUID) -> UUID:
    """Create a live read:classified grant so resolve_tier_grant resolves it."""
    grant = await storage.grant_clearance(
        grantee_user_id=user_id,
        granter_user_id=uuid4(),
        scope=ClearanceScope.READ_CLASSIFIED,
        reason="operator cleared for the classified case batch review",
        expires_at=datetime.now(tz=UTC) + timedelta(days=7),
        service="test",
        instance_id="t0",
    )
    return grant.id


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path


# --- manifest ---------------------------------------------------------------


async def test_manifest_happy_normal_mints_nonce(
    storage: BaseRepository, data_dir: Path, mkuser: Callable[..., CurrentUser]
) -> None:
    user = mkuser()
    doc_id, sha = await _seed_document(storage, data_dir)
    result = await documents_manifest(doc_id, user, storage)
    assert result.document_id == doc_id
    assert result.content_hash == sha
    assert result.tier is SensitivityTier.NORMAL
    assert result.content_size == len(_BLOB)
    assert result.access_nonce is not None


async def test_manifest_missing_document_is_404(
    storage: BaseRepository, mkuser: Callable[..., CurrentUser]
) -> None:
    with pytest.raises(ResourceNotFound):
        await documents_manifest(uuid4(), mkuser(), storage)


async def test_manifest_classified_without_scope_is_403(
    storage: BaseRepository, data_dir: Path, mkuser: Callable[..., CurrentUser]
) -> None:
    doc_id, _sha = await _seed_document(storage, data_dir, tier=SensitivityTier.CLASSIFIED)
    with pytest.raises(ScopeForbidden):
        await documents_manifest(doc_id, mkuser(), storage)


async def test_manifest_classified_with_scope_is_200(
    storage: BaseRepository, data_dir: Path, mkuser: Callable[..., CurrentUser]
) -> None:
    user = mkuser(ClearanceScope.READ_CLASSIFIED.value)
    doc_id, sha = await _seed_document(storage, data_dir, tier=SensitivityTier.CLASSIFIED)
    result = await documents_manifest(doc_id, user, storage)
    assert result.content_hash == sha
    assert result.tier is SensitivityTier.CLASSIFIED


# --- access -----------------------------------------------------------------


async def test_access_happy_normal_streams_journals_defangs(
    storage: BaseRepository, data_dir: Path, mkuser: Callable[..., CurrentUser]
) -> None:
    user = mkuser()
    private = await _register_key(storage, user.user_id)
    doc_id, sha = await _seed_document(storage, data_dir)
    nonce = (await documents_manifest(doc_id, user, storage)).access_nonce
    body = _signed_body(
        private, document_id=doc_id, content_hash=sha, nonce=nonce, signed_at=datetime.now(tz=UTC)
    )
    req = _FakeRequest(f"/v1/documents/{doc_id}/access")
    resp = await documents_access(doc_id, body, req, user, storage)  # type: ignore[arg-type]
    assert isinstance(resp, StreamingResponse)
    chunks = [chunk async for chunk in resp.body_iterator]
    served = b"".join(c if isinstance(c, bytes) else c.encode() for c in chunks)
    assert served == _BLOB
    # Defang headers protect the operator's frontend from hostile bytes.
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["Content-Security-Policy"] == (
        "default-src 'none'; sandbox; frame-ancestors 'self'"
    )
    assert resp.headers["Cache-Control"] == "no-store"
    assert resp.headers["X-Frame-Options"] == "SAMEORIGIN"
    assert resp.headers["Content-Disposition"].startswith("inline; filename=")
    # Exactly one tamper-evident journal row was appended; the chain is intact.
    rows = await _journal_rows(storage)
    assert len(rows) == 1
    assert rows[0].grant_id is None  # NORMAL rows require no grant
    assert await storage.verify_file_access_chain() is True


async def test_access_content_hash_mismatch_is_409(
    storage: BaseRepository, data_dir: Path, mkuser: Callable[..., CurrentUser]
) -> None:
    user = mkuser()
    private = await _register_key(storage, user.user_id)
    doc_id, _sha = await _seed_document(storage, data_dir)
    nonce = (await documents_manifest(doc_id, user, storage)).access_nonce
    body = _signed_body(
        private,
        document_id=doc_id,
        content_hash="c" * 64,
        nonce=nonce,
        signed_at=datetime.now(tz=UTC),
    )
    req = _FakeRequest(f"/v1/documents/{doc_id}/access")
    with pytest.raises(ConflictError):
        await documents_access(doc_id, body, req, user, storage)  # type: ignore[arg-type]
    assert await _journal_rows(storage) == []


async def test_access_no_registered_key_is_401(
    storage: BaseRepository, data_dir: Path, mkuser: Callable[..., CurrentUser]
) -> None:
    user = mkuser()  # no signing key registered for this user
    private = Ed25519PrivateKey.generate()
    doc_id, sha = await _seed_document(storage, data_dir)
    nonce = (await documents_manifest(doc_id, user, storage)).access_nonce
    body = _signed_body(
        private, document_id=doc_id, content_hash=sha, nonce=nonce, signed_at=datetime.now(tz=UTC)
    )
    req = _FakeRequest(f"/v1/documents/{doc_id}/access")
    with pytest.raises(AuthError):
        await documents_access(doc_id, body, req, user, storage)  # type: ignore[arg-type]
    assert await _journal_rows(storage) == []


async def test_access_classified_with_grant_journals_grant_id(
    storage: BaseRepository, data_dir: Path, mkuser: Callable[..., CurrentUser]
) -> None:
    user = mkuser(ClearanceScope.READ_CLASSIFIED.value)
    private = await _register_key(storage, user.user_id)
    grant_id = await _grant_read_classified(storage, user.user_id)
    doc_id, sha = await _seed_document(storage, data_dir, tier=SensitivityTier.CLASSIFIED)
    nonce = (await documents_manifest(doc_id, user, storage)).access_nonce
    body = _signed_body(
        private, document_id=doc_id, content_hash=sha, nonce=nonce, signed_at=datetime.now(tz=UTC)
    )
    req = _FakeRequest(f"/v1/documents/{doc_id}/access")
    resp = await documents_access(doc_id, body, req, user, storage)  # type: ignore[arg-type]
    chunks = [chunk async for chunk in resp.body_iterator]
    served = b"".join(c if isinstance(c, bytes) else c.encode() for c in chunks)
    assert served == _BLOB
    rows = await _journal_rows(storage)
    assert len(rows) == 1
    # The journal row names the exact grant that authorised the classified access.
    assert rows[0].grant_id == grant_id


async def test_access_missing_document_is_404(
    storage: BaseRepository, data_dir: Path, mkuser: Callable[..., CurrentUser]
) -> None:
    user = mkuser()
    private = await _register_key(storage, user.user_id)
    body = _signed_body(
        private,
        document_id=uuid4(),
        content_hash="a" * 64,
        nonce=uuid4(),
        signed_at=datetime.now(tz=UTC),
    )
    req = _FakeRequest("/v1/documents/x/access")
    with pytest.raises(ResourceNotFound):
        await documents_access(uuid4(), body, req, user, storage)  # type: ignore[arg-type]
    assert await _journal_rows(storage) == []
