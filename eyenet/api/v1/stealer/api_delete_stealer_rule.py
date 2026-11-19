# SPDX-License-Identifier: AGPL-3.0-or-later
"""DELETE /v1/stealer/rules/{rule_id}: remove a rule from disk.

Admin tier. Vendored rules that ship with the wheel can also be deleted
here, since EYENET_STEALER_RULES_DIR normally points at an operator-
owned directory in prod; in dev the vendored dir doubles as the active
catalog, and an accidental delete can be recovered from git.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from eyenet.api.deps import (
    CurrentUser,
    RequireScope,
    ResourceNotFound,
    get_audit,
    get_storage,
)
from eyenet.stealer.rules.catalog.rw import delete_rule, read_rule
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["stealer"])


@router.delete(
    "/stealer/rules/{rule_id}",
    operation_id="stealer_rules_delete",
    status_code=204,
)
async def stealer_rules_delete(
    rule_id: str,
    current_user: Annotated[CurrentUser, Depends(RequireScope("admin:stealer"))],
    _storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
) -> None:
    try:
        rule = read_rule(rule_id)
    except FileNotFoundError as exc:
        raise ResourceNotFound("stealer_rule") from exc
    try:
        delete_rule(rule_id)
    except FileNotFoundError as exc:
        raise ResourceNotFound("stealer_rule") from exc
    await audit.emit(
        event="eyenet.audit.stealer_rule.deleted",
        subject_kind="stealer_rule",
        evidence_ref=rule_id,
        system_user_id=current_user.user_id,
        payload={"family": rule.get("family"), "layer": rule.get("layer")},
    )
