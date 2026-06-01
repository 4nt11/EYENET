# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/sources — create (upsert) a Source (M9.D1)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, get_audit, get_storage
from eyenet.api.v1.schemas.sources import CreateSourceRequest, SourceDetail
from eyenet.api.v1.sources._detail import build_source_detail
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["sources"])


@router.post(
    "/sources",
    operation_id="sources_create",
    response_model=SourceDetail,
    status_code=201,
)
async def sources_create(
    body: CreateSourceRequest,
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:sources"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
) -> SourceDetail:
    now = datetime.now(tz=UTC)
    # upsert-by-(kind, display_name): a duplicate returns the existing row
    # (idempotent create — see CreateSourceRequest docstring).
    source_id = await storage.upsert_source(
        kind=body.kind,
        display_name=body.display_name,
        created_at=now,
    )
    if body.notes is not None:
        await storage.update_source(source_id=source_id, notes=body.notes)

    await audit.emit(
        event="eyenet.audit.source.created",
        subject_kind="source",
        subject_id=source_id,
        system_user_id=current_user.user_id,
        payload={"kind": body.kind.value, "display_name": body.display_name},
    )
    detail = await build_source_detail(storage, source_id)
    if detail is None:  # pragma: no cover — just-created row must exist
        raise RuntimeError("source vanished immediately after create")
    return detail
