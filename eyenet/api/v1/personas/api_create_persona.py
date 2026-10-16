# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/personas/standalone - create a persona from operator analysis.

A persona is normally FORMED by merging actors; but an operator may also assert one
directly from analysis (a labelled persona with no members yet, actors attached
later via merge). Distinct from ``POST /v1/personas`` (merge two actors). Personas
are not search-indexed, so this just creates + audits and returns the id.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, get_audit, get_storage
from eyenet.api.v1.schemas.operator_entities import CreatePersonaRequest, OperatorEntityCreated
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["personas"])


@router.post(
    "/personas/standalone",
    operation_id="personas_create",
    response_model=OperatorEntityCreated,
    status_code=201,
)
async def personas_create(
    body: CreatePersonaRequest,
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:persona_decision"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
) -> OperatorEntityCreated:
    persona_id = await storage.create_persona(label=body.label, now=datetime.now(tz=UTC))
    await audit.emit(
        event="eyenet.audit.persona.created",
        subject_kind="persona",
        subject_id=persona_id,
        system_user_id=current_user.user_id,
        payload={"label": body.label, "origin": "operator_analysis"},
    )
    return OperatorEntityCreated(id=persona_id, entity_type="persona")
