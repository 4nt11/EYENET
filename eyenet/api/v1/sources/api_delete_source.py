# SPDX-License-Identifier: AGPL-3.0-or-later
"""DELETE /v1/sources/{source_id} — delete an UNUSED source.

Refuses with 409 if anything still references the source (messages, groups,
actors, collectors, identities, candidates, relations, resolved artifacts); the
body names the blocking relations + counts so the operator knows what to detach
first. The source's own SourceDomains cascade. 204 on success.
"""

from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from eyenet.api.deps import CurrentUser, RequireScope, ResourceNotFound, get_audit, get_storage
from eyenet.contracts.source import SourceRow
from eyenet.storage.errors import ResourceInUseError
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["sources"])


@router.delete("/sources/{source_id}", operation_id="sources_delete", status_code=204)
async def sources_delete(
    source_id: UUID,
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:sources"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
) -> None:
    if cast("SourceRow | None", await storage.get_source(source_id)) is None:
        raise ResourceNotFound("source")
    try:
        await storage.delete_source(source_id)
    except ResourceInUseError as exc:
        raise HTTPException(
            status_code=409,
            detail={"reason": "source_in_use", "references": exc.refs},
        ) from exc
    await audit.emit(
        event="eyenet.audit.source.deleted",
        subject_kind="source",
        subject_id=source_id,
        system_user_id=current_user.user_id,
        payload={},
    )
