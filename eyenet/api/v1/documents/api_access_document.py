# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/documents/{document_id}/access — acknowledged raw-byte fetch.

Step 2 of the document access flow (mirrors the §5.6 attachment access path).
Clearance-gated, client-side Ed25519 signing, evidence-first serving:

  1. Resolve the document row (404 if missing); compute the effective tier.
  2. Clearance gate: enforce the tier's read:* scope and resolve the active
     grant id the journal requires on non-NORMAL rows. 403, no journal row, no
     bytes if the caller lacks clearance.
  3. ``expected_content_hash`` MUST equal the row's sha256 (serve-what-signed);
     mismatch -> 409.
  4. Resolve the operator's active signing key (401 if none) and fingerprint it.
  5. Recompute the acknowledgment body hash + the canonical, then record_access
     verifies the operator signature + freshness and chain-appends the journal
     row. Any failure -> 401, NO bytes.
  6. ONLY after the journal row is durably written, stream the RAW bytes from the
     row's storage_uri.

The bytes are potentially hostile (uploaded documents). The response is
defanged for inline viewing: ``X-Content-Type-Options: nosniff`` (no MIME
sniffing), a locked-down ``Content-Security-Policy`` (no scripts, sandboxed),
``Content-Disposition: inline`` with a sanitized filename, and ``no-store`` so
evidence is not cached by intermediaries. The frontend renders it inside its own
sandbox; the server refuses to help the payload execute.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from eyenet.api.deps import (
    AuthError,
    ConflictError,
    CurrentUser,
    ResourceNotFound,
    get_current_user,
    get_storage,
)
from eyenet.api.v1._clearance import resolve_tier_grant
from eyenet.api.v1._operator_signature import decode_operator_signature
from eyenet.api.v1.attachments._access_canonical import compute_access_body_hash
from eyenet.api.v1.schemas.attachments import FileAccessAcknowledgment
from eyenet.contracts.enums import FileServedVia
from eyenet.crypto import fingerprint, load_ed25519_public_key
from eyenet.storage.repository import BaseRepository
from eyenet.storage.sqlmodel_repo.file_access import FileAccessJournalError

router = APIRouter(tags=["documents"])

# Defang headers applied to every served document body. default-src 'none' +
# sandbox neutralizes scripts/plugins/top-nav even on direct navigation;
# frame-ancestors 'self' lets the operator's own frontend embed it for viewing.
_DEFANG_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'; sandbox; frame-ancestors 'self'",
    "Cache-Control": "no-store",
    "X-Frame-Options": "SAMEORIGIN",
}
# Content-Disposition filename: keep a conservative charset, no CR/LF/quotes that
# could break the header or forge extra directives.
_UNSAFE_FILENAME = re.compile(r"[^\w.\- ]+")


def _safe_disposition_filename(filename: str | None, document_id: UUID) -> str:
    """A header-safe inline filename, falling back to the document id."""
    if filename:
        cleaned = _UNSAFE_FILENAME.sub("_", filename).strip("_ ")
        if cleaned:
            return cleaned[:200]
    return f"document-{document_id}"


@router.post(
    "/documents/{document_id}/access",
    operation_id="documents_access",
    response_class=StreamingResponse,
    status_code=200,
)
async def documents_access(
    document_id: UUID,
    body: FileAccessAcknowledgment,
    request: Request,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    storage: Annotated[BaseRepository, Depends(get_storage)],
) -> StreamingResponse:
    # (a) Resolve the row + effective tier.
    row = await storage.get_document(document_id)
    if row is None:
        raise ResourceNotFound(f"document:{document_id}")

    effective_tier = row.operator_tier_override or row.classifier_tier
    # (b) Clearance gate: enforce read:* for the tier AND resolve the active grant
    # id the journal REQUIRES on every non-NORMAL row. 403 before any bytes.
    grant_id = await resolve_tier_grant(current_user, storage, effective_tier)

    # (c) Serve-what-signed: the client must be asking for THIS document's content.
    if body.expected_content_hash != row.sha256:
        raise ConflictError("expected_content_hash does not match the stored document")

    # (d) Resolve the operator's active signing key (no client kid).
    verifying_key_bytes = await storage.active_signing_key_for(current_user.user_id)
    if verifying_key_bytes is None:
        raise AuthError("no_active_signing_key")
    verifying_key = load_ed25519_public_key(verifying_key_bytes)
    if verifying_key is None:
        raise AuthError("active_signing_key_unloadable")
    active_fingerprint = fingerprint(verifying_key)

    # (e) Decode the detached operator signature.
    operator_signature = decode_operator_signature(body.operator_signature)

    # (f) Reconstruct the signed inputs and journal the access (verify + chain).
    body_hash = compute_access_body_hash(body.model_dump())
    content_hash_bytes = bytes.fromhex(row.sha256)
    try:
        await storage.record_access(
            user_id=current_user.user_id,
            audit_event_id=None,
            grant_id=grant_id,
            # The manifest-minted single-use nonce is consumed atomically with the
            # journal append (and is signed into body_hash), closing the replay hole.
            acknowledgment_id=body.access_nonce,
            content_hash=content_hash_bytes,
            content_size=row.size_bytes,
            content_mime=row.mime,
            tier=effective_tier,
            served_via=FileServedVia.ATTACHMENT_STREAM,
            signing_pubkey_fingerprint=active_fingerprint,
            operator_signature=operator_signature,
            sig_method="POST",
            sig_url=request.url.path,
            sig_request_id=body.request_id,
            sig_timestamp=body.signed_at.isoformat(),
            sig_body_hash=body_hash,
            now=datetime.now(tz=UTC),
        )
    except FileAccessJournalError as exc:
        # Signature/freshness/key verification failed -> 401 (no oracle), no bytes.
        raise AuthError("file_access_verification_failed") from exc

    # (g) Bytes flow ONLY after the journal row is durably written.
    if row.storage_uri is None:
        raise ResourceNotFound(f"document:{document_id}:bytes")
    blob_path = Path(row.storage_uri)

    async def _iter_bytes() -> AsyncIterator[bytes]:
        # Read from the ROW's storage_uri only. Off-thread: the blocking disk read
        # must not stall the event loop.
        payload = await asyncio.to_thread(blob_path.read_bytes)
        yield payload

    headers = {
        **_DEFANG_HEADERS,
        "Content-Disposition": (
            f'inline; filename="{_safe_disposition_filename(row.filename, document_id)}"'
        ),
    }
    return StreamingResponse(_iter_bytes(), media_type=row.mime, headers=headers)
