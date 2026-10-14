# SPDX-License-Identifier: AGPL-3.0-or-later
"""DELETE /v1/indicators/rules/{rule_id} — remove an operator-custom rule.

Vendored rules cannot be deleted (they would reappear on the next vendored-catalog
seed) — disable them with PATCH instead. Deleting is an admin-tier action, matching
collector deletion.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from eyenet.api.deps import (
    ConflictError,
    CurrentUser,
    RequireScope,
    ResourceNotFound,
    get_audit,
    get_storage,
)
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["indicators"])


@router.delete(
    "/indicators/rules/{rule_id}",
    operation_id="indicator_rules_delete",
    status_code=204,
)
async def indicator_rules_delete(
    rule_id: UUID,
    current_user: Annotated[CurrentUser, Depends(RequireScope("admin:collectors"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
) -> None:
    rule = await storage.get_indicator_rule(rule_id)
    if rule is None:
        raise ResourceNotFound("indicator_rule")
    if rule.vendored:
        raise ConflictError("vendored rules cannot be deleted; disable them with PATCH instead")
    await storage.delete_indicator_rule(rule_id)
    await audit.emit(
        event="eyenet.audit.indicator_rule.deleted",
        subject_kind="indicator_rule",
        subject_id=rule_id,
        system_user_id=current_user.user_id,
        payload={"kind": rule.kind, "pattern": rule.pattern},
    )
