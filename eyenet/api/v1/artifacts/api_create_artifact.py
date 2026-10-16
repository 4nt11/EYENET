# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/artifacts — create an operator-asserted artifact (exploration canvas).

A hand-added infrastructure artifact (onion / domain / wallet / ...). Deduped by
value_hash: asserting an already-collected artifact returns the existing row (and
keeps its provenance). Emits ``entity.artifact.changed`` for the SearchIndexer.
Uses ``write:graph`` (there is no ``write:artifacts`` scope; artifact writes ride
the graph scope).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, get_audit, get_publisher, get_storage
from eyenet.api.v1.schemas.operator_entities import (
    CreateOperatorArtifactRequest,
    OperatorEntityCreated,
)
from eyenet.bus.publisher import BusEnvelopePublisher
from eyenet.search_indexer.events import publish_entity_changed
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["artifacts"])


@router.post(
    "/artifacts",
    operation_id="artifacts_create",
    response_model=OperatorEntityCreated,
    status_code=201,
)
async def artifacts_create(
    body: CreateOperatorArtifactRequest,
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:graph"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
    publisher: Annotated[BusEnvelopePublisher, Depends(get_publisher)],
) -> OperatorEntityCreated:
    artifact_id = await storage.create_operator_artifact(kind=body.kind, value=body.value)
    await publish_entity_changed(publisher, entity_type="artifact", entity_id=artifact_id)
    await audit.emit(
        event="eyenet.audit.artifact.created",
        subject_kind="artifact",
        subject_id=artifact_id,
        system_user_id=current_user.user_id,
        payload={"provenance": "operator_asserted", "kind": body.kind, "value": body.value},
    )
    return OperatorEntityCreated(id=artifact_id, entity_type="artifact")
