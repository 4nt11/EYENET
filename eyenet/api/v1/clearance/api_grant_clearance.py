# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/clearance/grants — grant a clearance scope (§4.8). Requires admin:clearance."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header

from eyenet.api.deps import (
    CurrentUser,
    RequireScope,
    UnprocessableError,
    get_audit,
    get_storage,
)
from eyenet.api.v1.schemas.clearance import ClearanceGrantDetail, ClearanceGrantRequest
from eyenet.storage.errors import ClearanceGrantError
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["clearance"])


@router.post(
    "/clearance/grants",
    operation_id="clearance_grant",
    response_model=ClearanceGrantDetail,
    status_code=201,
)
async def clearance_grant(
    body: ClearanceGrantRequest,
    current_user: Annotated[CurrentUser, Depends(RequireScope("admin:clearance"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
    idempotency_key: Annotated[  # noqa: ARG001 — read by IdempotencyMiddleware; declared for the OpenAPI surface
        str | None, Header(alias="Idempotency-Key", max_length=128)
    ] = None,
) -> ClearanceGrantDetail:
    try:
        row = await storage.grant_clearance(
            grantee_user_id=body.user_id,
            granter_user_id=current_user.user_id,
            scope=body.scope,
            reason=body.reason,
            expires_at=body.expires_at,
            service=audit.service,
            instance_id=audit.instance_id,
        )
    except ClearanceGrantError as exc:
        raise UnprocessableError(str(exc)) from exc
    return ClearanceGrantDetail.from_domain(row, now=datetime.now(tz=UTC))
