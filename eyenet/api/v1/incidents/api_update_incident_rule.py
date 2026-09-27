# SPDX-License-Identifier: AGPL-3.0-or-later
"""PATCH /v1/incident-rules/{rule_id} — edit a rule. Requires admin:incident_rules.

Only provided fields change. A new pattern/label is re-validated (422); an unknown rule
is 404. Enable/disable is a field update, so a rule can be toggled without deletion.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from eyenet.api.deps import (
    CurrentUser,
    RequireScope,
    ResourceNotFound,
    UnprocessableError,
    get_storage,
)
from eyenet.api.v1.incidents._rules_shared import WRITE_SCOPE, rule_out
from eyenet.api.v1.schemas.incidents import IncidentRuleOut, IncidentRuleUpdate
from eyenet.incidents import rules
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["incidents"])


@router.patch(
    "/incident-rules/{rule_id}",
    operation_id="update_incident_rule",
    response_model=IncidentRuleOut,
)
async def update_incident_rule(
    rule_id: UUID,
    body: IncidentRuleUpdate,
    _: Annotated[CurrentUser, Depends(RequireScope(WRITE_SCOPE))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
) -> IncidentRuleOut:
    fields = body.model_dump(exclude_none=True)
    if not fields:
        raise UnprocessableError("no fields to update")
    if "pattern" in fields:
        err = rules.validate_pattern(fields["pattern"])
        if err is not None:
            raise UnprocessableError(f"invalid RE2 pattern: {err}")
    if "label" in fields and fields["label"] not in rules.TAXONOMY_LABELS:
        raise UnprocessableError(f"label must be one of {sorted(rules.TAXONOMY_LABELS)}")

    if not await storage.update_incident_rule(rule_id, fields):
        raise ResourceNotFound(f"incident rule {rule_id} not found")
    updated = await storage.get_incident_rule(rule_id)
    return rule_out(updated)
