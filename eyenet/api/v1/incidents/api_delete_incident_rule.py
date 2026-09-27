# SPDX-License-Identifier: AGPL-3.0-or-later
"""DELETE /v1/incident-rules/{rule_id} — remove a rule. Requires admin:incident_rules."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, ResourceNotFound, get_storage
from eyenet.api.v1.incidents._rules_shared import WRITE_SCOPE
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["incidents"])


@router.delete("/incident-rules/{rule_id}", operation_id="delete_incident_rule", status_code=204)
async def delete_incident_rule(
    rule_id: UUID,
    _: Annotated[CurrentUser, Depends(RequireScope(WRITE_SCOPE))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
) -> None:
    if not await storage.delete_incident_rule(rule_id):
        raise ResourceNotFound(f"incident rule {rule_id} not found")
