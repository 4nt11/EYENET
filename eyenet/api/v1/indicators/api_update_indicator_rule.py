# SPDX-License-Identifier: AGPL-3.0-or-later
"""PATCH /v1/indicators/rules/{rule_id} — toggle enabled / edit description.

Works for vendored and custom rules alike: disabling a vendored rule is the
Wazuh-style override (it survives vendored-catalog upgrades). Pattern and kind are
immutable here — change a custom rule by delete + recreate.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, ResourceNotFound, get_audit, get_storage
from eyenet.api.v1.schemas.indicators import IndicatorRuleOut, IndicatorRuleUpdate
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["indicators"])


@router.patch(
    "/indicators/rules/{rule_id}",
    operation_id="indicator_rules_update",
    response_model=IndicatorRuleOut,
)
async def indicator_rules_update(
    rule_id: UUID,
    body: IndicatorRuleUpdate,
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:collectors"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
) -> IndicatorRuleOut:
    row = await storage.update_indicator_rule(
        rule_id=rule_id,
        enabled=body.enabled,
        description=body.description,
    )
    if row is None:
        raise ResourceNotFound("indicator_rule")
    await audit.emit(
        event="eyenet.audit.indicator_rule.updated",
        subject_kind="indicator_rule",
        subject_id=rule_id,
        system_user_id=current_user.user_id,
        payload={"fields": sorted(body.model_fields_set)},
    )
    return IndicatorRuleOut.from_row(row)
