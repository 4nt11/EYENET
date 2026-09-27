# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/incident-rules — list operator-defined detection rules. Requires read:incidents."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from eyenet.api.deps import CurrentUser, RequireScope, get_storage
from eyenet.api.v1.incidents._rules_shared import rule_out
from eyenet.api.v1.schemas.incidents import IncidentRuleOut
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["incidents"])


@router.get(
    "/incident-rules", operation_id="list_incident_rules", response_model=list[IncidentRuleOut]
)
async def list_incident_rules(
    _: Annotated[CurrentUser, Depends(RequireScope("read:incidents"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    enabled_only: Annotated[bool, Query()] = False,
) -> list[IncidentRuleOut]:
    rows = await storage.list_incident_rules(enabled_only=enabled_only)
    return [rule_out(r) for r in rows]
