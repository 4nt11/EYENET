# SPDX-License-Identifier: AGPL-3.0-or-later
"""PATCH /v1/sources/{source_id} — update editable Source fields (M9.D1).

``display_name`` / ``notes`` go through ``update_source``; ``canonical_url``
through ``set_source_canonical_url`` (which enforces the primary-domain
invariant — a rejection surfaces as 422 via the app's
``SourceCanonicalUrlError`` handler). Only fields present in the request body
are applied (``model_fields_set``); ``canonical_url`` may be sent as null to clear.
"""

from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, ResourceNotFound, get_audit, get_storage
from eyenet.api.v1.schemas.sources import SourceDetail, UpdateSourceRequest
from eyenet.api.v1.sources._detail import build_source_detail
from eyenet.contracts.source import SourceRow
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["sources"])


@router.patch(
    "/sources/{source_id}",
    operation_id="sources_update",
    response_model=SourceDetail,
    status_code=200,
)
async def sources_update(
    source_id: UUID,
    body: UpdateSourceRequest,
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:sources"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
) -> SourceDetail:
    if cast("SourceRow | None", await storage.get_source(source_id)) is None:
        raise ResourceNotFound("source")

    fields = body.model_fields_set
    if "display_name" in fields or "notes" in fields:
        await storage.update_source(
            source_id=source_id,
            display_name=body.display_name if "display_name" in fields else None,
            notes=body.notes if "notes" in fields else None,
        )
    if "canonical_url" in fields:
        # May raise SourceCanonicalUrlError → 422 (app handler).
        await storage.set_source_canonical_url(
            source_id=source_id,
            canonical_url=body.canonical_url,
        )

    await audit.emit(
        event="eyenet.audit.source.updated",
        subject_kind="source",
        subject_id=source_id,
        system_user_id=current_user.user_id,
        payload={"fields": sorted(fields)},
    )
    detail = await build_source_detail(storage, source_id)
    if detail is None:  # pragma: no cover — existence checked above
        raise ResourceNotFound("source")
    return detail
