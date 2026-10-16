# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/actors — create an operator-asserted actor (exploration canvas).

A hand-created actor no collector produced. Carries ``provenance="operator_asserted"``
and hangs off the synthetic operator source. Emits ``entity.actor.changed`` so the
SearchIndexer makes it findable, and audits the create.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, get_audit, get_publisher, get_storage
from eyenet.api.v1.schemas.operator_entities import (
    CreateOperatorActorRequest,
    OperatorEntityCreated,
)
from eyenet.bus.publisher import BusEnvelopePublisher
from eyenet.search_indexer.events import publish_entity_changed
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["actors"])


@router.post(
    "/actors",
    operation_id="actors_create",
    response_model=OperatorEntityCreated,
    status_code=201,
)
async def actors_create(
    body: CreateOperatorActorRequest,
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:actors"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
    publisher: Annotated[BusEnvelopePublisher, Depends(get_publisher)],
) -> OperatorEntityCreated:
    actor_id = await storage.create_operator_actor(
        handle=body.handle, display_name=body.display_name
    )
    await publish_entity_changed(publisher, entity_type="actor", entity_id=actor_id)
    await audit.emit(
        event="eyenet.audit.actor.created",
        subject_kind="actor",
        subject_id=actor_id,
        system_user_id=current_user.user_id,
        payload={
            "provenance": "operator_asserted",
            "handle": body.handle,
            "display_name": body.display_name,
        },
    )
    return OperatorEntityCreated(id=actor_id, entity_type="actor")
