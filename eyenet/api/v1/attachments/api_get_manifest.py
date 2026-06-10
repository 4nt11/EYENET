# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/attachments/{blob_id}/manifest — metadata only, no bytes (§5.6 step 1).

PHASE-5: NORMAL-tier only. A non-NORMAL effective tier fails CLOSED with 403
("clearance gating not yet implemented" — PHASE-6) and leaks NO metadata. For
NORMAL rows the handler mints a fresh single-use acknowledgment nonce (a new
one each call) and returns the safe :class:`FileManifest` envelope. Calling
this endpoint appends NO file-access-journal row — it is not access.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from eyenet.api.deps import (
    CurrentUser,
    ResourceNotFound,
    ScopeForbidden,
    get_current_user,
    get_storage,
)
from eyenet.api.v1.schemas.attachments import FileManifest
from eyenet.contracts.enums import SensitivityTier
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["attachments"])

# Mirrors storage ``_ACK_TTL`` (§5.6 — acknowledgment nonces live 60s).
_ACK_TTL = timedelta(seconds=60)


@router.get(
    "/attachments/{blob_id}/manifest",
    operation_id="attachments_manifest",
    response_model=FileManifest,
    status_code=200,
)
async def attachments_manifest(
    blob_id: UUID,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    storage: Annotated[BaseRepository, Depends(get_storage)],
) -> FileManifest:
    row = await storage.get_attachment(blob_id)
    if row is None:
        raise ResourceNotFound(f"attachment:{blob_id}")

    effective_tier = row.operator_tier_override or row.classifier_tier
    if effective_tier is not SensitivityTier.NORMAL:
        # FAIL CLOSED: clearance gating for non-NORMAL tiers is PHASE-6. Do not
        # leak classified metadata (hash/size/mime) through the manifest.
        raise ScopeForbidden("clearance gating not yet implemented")

    now = datetime.now(tz=UTC)
    access_nonce = await storage.record_acknowledgment(
        current_user.user_id,
        row.sha256,
        now=now,
    )
    return FileManifest(
        blob_id=blob_id,
        content_hash=row.sha256,
        content_size=row.size_bytes,
        content_mime=row.mime,
        tier=effective_tier,
        source_subject_id=row.message_id,
        source_subject_kind="message",
        collected_at=now,
        access_nonce=access_nonce,
        nonce_expires_at=now + _ACK_TTL,
    )
