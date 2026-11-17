# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/stealer/rules: create a new rule, atomic write-to-disk."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from eyenet.api.deps import (
    ConflictError,
    CurrentUser,
    RequireScope,
    get_audit,
    get_storage,
)
from eyenet.api.v1.schemas.stealer_rules import StealerRuleIn, StealerRuleOut
from eyenet.stealer.rules.catalog.rw import write_rule
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["stealer"])


@router.post(
    "/stealer/rules",
    operation_id="stealer_rules_create",
    response_model=StealerRuleOut,
    status_code=201,
)
async def stealer_rules_create(
    body: StealerRuleIn,
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:stealer"))],
    _storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
) -> StealerRuleOut:
    payload = body.model_dump(exclude_none=True, by_alias=True)
    try:
        stored = write_rule(payload, allow_overwrite=False)
    except FileExistsError as exc:
        raise ConflictError(f"rule {body.id!r} already exists; use PUT to update") from exc
    except ValueError as exc:
        raise ConflictError(str(exc)) from exc
    await audit.emit(
        event="eyenet.audit.stealer_rule.created",
        subject_kind="stealer_rule",
        subject_id=body.id,
        system_user_id=current_user.user_id,
        payload={"family": body.family, "layer": body.layer, "priority": body.priority},
    )
    return StealerRuleOut.model_validate(stored)
