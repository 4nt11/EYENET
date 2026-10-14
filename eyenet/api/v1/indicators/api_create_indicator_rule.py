# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/indicators/rules — create an operator-custom extraction rule.

``kind`` + ``pattern`` are validated by the request schema (known kind, compiles
under RE2). A duplicate ``(kind, pattern)`` surfaces as 409 via the app's
IntegrityError handler.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, get_audit, get_storage
from eyenet.api.v1.schemas.indicators import IndicatorRuleCreate, IndicatorRuleOut
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["indicators"])


@router.post(
    "/indicators/rules",
    operation_id="indicator_rules_create",
    response_model=IndicatorRuleOut,
    status_code=201,
)
async def indicator_rules_create(
    body: IndicatorRuleCreate,
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:collectors"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
) -> IndicatorRuleOut:
    row = await storage.create_indicator_rule(
        kind=body.kind,
        pattern=body.pattern,
        fold_case=body.fold_case,
        description=body.description,
        enabled=body.enabled,
    )
    await audit.emit(
        event="eyenet.audit.indicator_rule.created",
        subject_kind="indicator_rule",
        subject_id=row.id,
        system_user_id=current_user.user_id,
        payload={"kind": row.kind, "pattern": row.pattern},
    )
    return IndicatorRuleOut.from_row(row)
