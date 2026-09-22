# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/attachments/{blob_id}/access — acknowledged binary fetch (§5.6 step 2).

Clearance-gated, client-side Ed25519 signing, evidence-first serving.

Flow:
  1. Resolve the blob row (404 if missing); compute the effective tier.
  2. Clearance gate (§4.6-4.8): enforce the tier's read:* scope and resolve the
     active grant id the journal requires on non-NORMAL rows. 403, no journal
     row, no bytes if the caller lacks clearance.
  3. ``expected_content_hash`` MUST equal the row's sha256 (serve-what-signed);
     mismatch → 409.
  4. Resolve the operator's active signing key (401 if none registered) and
     fingerprint it server-side (no client ``kid``).
  5. Recompute the acknowledgment body hash (signature EXCLUDED) and the §5.7
     canonical, then call :meth:`record_access` with a tz-AWARE ``now``. That
     verifies the operator signature + freshness and chain-appends the journal
     row. Any failure → 401, NO bytes.
  6. ONLY after the journal row is durably written, stream the bytes from the
     ROW's ``storage_uri`` (never a client-supplied path) as
     ``attachment_stream``. A post-journal read failure is a 500 but the access
     IS recorded (evidence-first, §5.5).
"""

from __future__ import annotations

import asyncio
import base64
import binascii
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
from eyenet.api.v1.attachments._access_canonical import compute_access_body_hash
from eyenet.api.v1.schemas.attachments import FileAccessAcknowledgment
from eyenet.contracts.enums import FileServedVia
from eyenet.crypto import fingerprint, load_ed25519_public_key
from eyenet.storage.repository import BaseRepository
from eyenet.storage.sqlmodel_repo.file_access import FileAccessJournalError

router = APIRouter(tags=["attachments"])

_SIG_PREFIX = "ed25519:"
_ED25519_SIG_LEN = 64


def _decode_operator_signature(operator_signature: str) -> bytes:
    """Decode the ``ed25519:<urlsafe-b64>`` wire form into 64 raw bytes.

    A malformed prefix or base64 payload is a 401-class auth failure (no
    oracle), never an unhandled crash.
    """
    if not operator_signature.startswith(_SIG_PREFIX):
        raise AuthError("operator_signature_malformed_prefix")
    encoded = operator_signature[len(_SIG_PREFIX) :]
    try:
        raw = base64.urlsafe_b64decode(encoded)
    except (ValueError, binascii.Error) as exc:
        raise AuthError("operator_signature_b64_invalid") from exc
    if len(raw) != _ED25519_SIG_LEN:
        raise AuthError("operator_signature_length_invalid")
    return raw


@router.post(
    "/attachments/{blob_id}/access",
    operation_id="attachments_access",
    response_class=StreamingResponse,
    status_code=200,
)
async def attachments_access(
    blob_id: UUID,
    body: FileAccessAcknowledgment,
    request: Request,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    storage: Annotated[BaseRepository, Depends(get_storage)],
) -> StreamingResponse:
    # (a) Resolve the blob row + effective tier.
    row = await storage.get_attachment(blob_id)
    if row is None:
        raise ResourceNotFound(f"attachment:{blob_id}")

    effective_tier = row.operator_tier_override or row.classifier_tier
    # Clearance gate (§4.6-4.8): enforce read:* for the tier AND resolve the active
    # grant id the journal REQUIRES on every non-NORMAL row. 403 before any bytes.
    grant_id = await resolve_tier_grant(current_user, storage, effective_tier)

    # (b) Serve-what-signed: the client must be asking for THIS blob's content.
    if body.expected_content_hash != row.sha256:
        raise ConflictError("expected_content_hash does not match the stored blob")

    # (c) Resolve the operator's active signing key (no client kid).
    verifying_key_bytes = await storage.active_signing_key_for(current_user.user_id)
    if verifying_key_bytes is None:
        raise AuthError("no_active_signing_key")
    verifying_key = load_ed25519_public_key(verifying_key_bytes)
    if verifying_key is None:
        raise AuthError("active_signing_key_unloadable")
    active_fingerprint = fingerprint(verifying_key)

    # (d) Decode the detached operator signature.
    operator_signature = _decode_operator_signature(body.operator_signature)

    # (e) Reconstruct the signed inputs and journal the access (verify + chain).
    sig_url = request.url.path
    body_hash = compute_access_body_hash(body.model_dump())
    content_hash_bytes = bytes.fromhex(row.sha256)
    try:
        await storage.record_access(
            user_id=current_user.user_id,
            audit_event_id=None,
            # Resolved active grant (None for NORMAL). The journal CHECK requires a
            # grant_id on every non-NORMAL row; the gate above guarantees it is set.
            grant_id=grant_id,
            # FIX 2: pass the manifest-minted single-use nonce so record_access
            # CONSUMES it atomically with the journal append (closing the replay
            # hole). The nonce is also signed into the body_hash, so a replay of
            # this exact POST is rejected — the nonce is already burned.
            acknowledgment_id=body.access_nonce,
            content_hash=content_hash_bytes,
            content_size=row.size_bytes,
            content_mime=row.mime,
            tier=effective_tier,
            served_via=FileServedVia.ATTACHMENT_STREAM,
            signing_pubkey_fingerprint=active_fingerprint,
            operator_signature=operator_signature,
            sig_method="POST",
            sig_url=sig_url,
            sig_request_id=body.request_id,
            sig_timestamp=body.signed_at.isoformat(),
            sig_body_hash=body_hash,
            now=datetime.now(tz=UTC),
        )
    except FileAccessJournalError as exc:
        # Signature/freshness/key verification failed → 401 (no oracle), no bytes.
        raise AuthError("file_access_verification_failed") from exc

    # (f) §5.5 — bytes flow ONLY after the journal row is durably written.
    if row.storage_uri is None:
        # The journal records the access; the bytes are simply not retained.
        raise ResourceNotFound(f"attachment:{blob_id}:bytes")
    blob_path = Path(row.storage_uri)

    async def _iter_bytes() -> AsyncIterator[bytes]:
        # Read from the ROW's storage_uri only — never a client-supplied path.
        # Off-thread (ASYNC230): the blocking disk read must not stall the loop.
        payload = await asyncio.to_thread(blob_path.read_bytes)
        yield payload

    return StreamingResponse(_iter_bytes(), media_type=row.mime)
