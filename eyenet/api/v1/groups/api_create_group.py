# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/groups — create an operator-asserted group (exploration canvas).

A hand-created group no collector produced. Carries ``provenance="operator_asserted"``
and hangs off the synthetic operator source. Emits ``entity.group.changed`` for the
SearchIndexer and audits the create.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, get_audit, get_publisher, get_storage
from eyenet.api.v1.schemas.operator_entities import (
    CreateOperatorGroupRequest,
    OperatorEntityCreated,
)
from eyenet.bus.publisher import BusEnvelopePublisher
from eyenet.search_indexer.events import publish_entity_changed
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["groups"])


@router.post(
    "/groups",
    operation_id="groups_create",
    response_model=OperatorEntityCreated,
    status_code=201,
)
async def groups_create(
    body: CreateOperatorGroupRequest,
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:groups"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
    publisher: Annotated[BusEnvelopePublisher, Depends(get_publisher)],
) -> OperatorEntityCreated:
    group_id = await storage.create_operator_group(title=body.title, kind=body.kind)
    await publish_entity_changed(publisher, entity_type="group", entity_id=group_id)
    await audit.emit(
        event="eyenet.audit.group.created",
        subject_kind="group",
        subject_id=group_id,
        system_user_id=current_user.user_id,
        payload={"provenance": "operator_asserted", "title": body.title, "kind": body.kind.value},
    )
    return OperatorEntityCreated(id=group_id, entity_type="group")
