# SPDX-License-Identifier: AGPL-3.0-or-later
"""PUT /v1/stealer/rules/{rule_id}: replace a rule in place.

Full-replace semantics (PUT, not PATCH). The URL slug MUST match the body
id to prevent accidental renames via body-only edits; a rename is a
DELETE + POST.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from eyenet.api.deps import (
    ConflictError,
    CurrentUser,
    RequireScope,
    ResourceNotFound,
    get_audit,
    get_storage,
)
from eyenet.api.v1.schemas.stealer_rules import StealerRuleIn, StealerRuleOut
from eyenet.stealer.rules.catalog.rw import read_rule, write_rule
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["stealer"])


@router.put(
    "/stealer/rules/{rule_id}",
    operation_id="stealer_rules_update",
    response_model=StealerRuleOut,
)
async def stealer_rules_update(
    rule_id: str,
    body: StealerRuleIn,
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:stealer"))],
    _storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
) -> StealerRuleOut:
    if body.id != rule_id:
        raise ConflictError(f"body.id {body.id!r} does not match URL slug {rule_id!r}")
    try:
        read_rule(rule_id)
    except FileNotFoundError as exc:
        raise ResourceNotFound("stealer_rule") from exc
    payload = body.model_dump(exclude_none=True, by_alias=True)
    try:
        stored = write_rule(payload, allow_overwrite=True)
    except ValueError as exc:
        raise ConflictError(str(exc)) from exc
    await audit.emit(
        event="eyenet.audit.stealer_rule.updated",
        subject_kind="stealer_rule",
        evidence_ref=rule_id,
        system_user_id=current_user.user_id,
        payload={"family": body.family, "layer": body.layer, "priority": body.priority},
    )
    return StealerRuleOut.model_validate(stored)
