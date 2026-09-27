# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/incident-rules — add an operator detection rule. Requires admin:incident_rules.

Validates the RE2 pattern (422 if uncompilable), the label (422 if not a taxonomy head),
and the name (409 if it collides with a built-in signal or an existing rule).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends

from eyenet.api.deps import ConflictError, CurrentUser, RequireScope, get_storage
from eyenet.api.v1.incidents._rules_shared import (
    WRITE_SCOPE,
    rule_out,
    validate_name,
    validate_pattern_and_label,
)
from eyenet.api.v1.schemas.incidents import IncidentRuleCreate, IncidentRuleOut
from eyenet.contracts.incident import IncidentRuleRow
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["incidents"])


@router.post(
    "/incident-rules",
    operation_id="create_incident_rule",
    response_model=IncidentRuleOut,
    status_code=201,
)
async def create_incident_rule(
    body: IncidentRuleCreate,
    current_user: Annotated[CurrentUser, Depends(RequireScope(WRITE_SCOPE))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
) -> IncidentRuleOut:
    validate_pattern_and_label(body.pattern, body.label)
    validate_name(body.name)
    existing = await storage.list_incident_rules()
    if any(r.name == body.name for r in existing):
        raise ConflictError(f"rule name {body.name!r} already exists")
    row = IncidentRuleRow(
        name=body.name,
        pattern=body.pattern,
        label=body.label,
        weight=body.weight,
        enabled=body.enabled,
        description=body.description,
        created_by=current_user.username,
        created_at=datetime.now(tz=UTC),
    )
    await storage.create_incident_rule(row)
    return rule_out(row)
