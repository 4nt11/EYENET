# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/documents/{document_id}/manifest — metadata only, no bytes.

Step 1 of the two-step document access flow (mirrors the §5.6 attachment
manifest). Clearance-gated: NORMAL is open to any authenticated caller;
RESTRICTED/CLASSIFIED require the matching ``read:*`` scope or the request 403s
BEFORE leaking any metadata. For readable rows the handler mints a fresh
single-use acknowledgment nonce and returns the safe :class:`DocumentManifest`
envelope (metadata + redacted classification + the nonce). Calling this endpoint
appends NO file-access-journal row: it is not access.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, ResourceNotFound, get_current_user, get_storage
from eyenet.api.v1._clearance import enforce_tier_clearance
from eyenet.api.v1.schemas.documents import DocumentManifest
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["documents"])

# Mirrors storage ``_ACK_TTL`` (acknowledgment nonces live 60s).
_ACK_TTL = timedelta(seconds=60)


@router.get(
    "/documents/{document_id}/manifest",
    operation_id="documents_manifest",
    response_model=DocumentManifest,
    status_code=200,
)
async def documents_manifest(
    document_id: UUID,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    storage: Annotated[BaseRepository, Depends(get_storage)],
) -> DocumentManifest:
    row = await storage.get_document(document_id)
    if row is None:
        raise ResourceNotFound(f"document:{document_id}")

    effective_tier = row.operator_tier_override or row.classifier_tier
    # Clearance gate: 403 before any metadata leaks if the caller lacks the
    # read:* scope for this tier. NORMAL passes for any authenticated caller.
    enforce_tier_clearance(current_user, effective_tier)

    now = datetime.now(tz=UTC)
    access_nonce = await storage.record_acknowledgment(
        current_user.user_id,
        row.sha256,
        now=now,
    )
    return DocumentManifest(
        document_id=document_id,
        content_hash=row.sha256,
        content_size=row.size_bytes,
        content_mime=row.mime,
        tier=effective_tier,
        filename=row.filename,
        doc_kind=row.doc_kind,
        review_required=row.review_required,
        classification=row.classification,
        uploaded_at=row.uploaded_at,
        ingested_at=row.ingested_at,
        access_nonce=access_nonce,
        nonce_expires_at=now + _ACK_TTL,
    )
