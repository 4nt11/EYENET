# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/clearance/grants/{grant_id}/revoke — revoke a clearance grant (§4.8).

Requires admin:clearance. Revocation is applied synchronously and self-audited
by storage (`CLEARANCE_REVOKED`); the 202 `WriteAccepted` mirrors the shared
operator-write envelope for client uniformity.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header

from eyenet.api.deps import (
    CurrentUser,
    RequireScope,
    ResourceNotFound,
    UnprocessableError,
    get_audit,
    get_storage,
)
from eyenet.api.v1.schemas.clearance import ClearanceRevokeRequest
from eyenet.api.v1.schemas.writes import WriteAccepted
from eyenet.contracts.audit_subjects import AuditSubject
from eyenet.storage.errors import ClearanceGrantError
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["clearance"])


@router.post(
    "/clearance/grants/{grant_id}/revoke",
    operation_id="clearance_revoke_grant",
    response_model=WriteAccepted,
    status_code=202,
)
async def clearance_revoke_grant(
    grant_id: UUID,
    body: ClearanceRevokeRequest,
    current_user: Annotated[CurrentUser, Depends(RequireScope("admin:clearance"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
    idempotency_key: Annotated[  # noqa: ARG001 — read by IdempotencyMiddleware; declared for the OpenAPI surface
        str | None, Header(alias="Idempotency-Key", max_length=128)
    ] = None,
) -> WriteAccepted:
    if await storage.get_clearance_grant(grant_id) is None:
        raise ResourceNotFound("clearance grant")
    try:
        row = await storage.revoke_clearance(
            grant_id=grant_id,
            revoker_user_id=current_user.user_id,
            reason=body.revocation_reason,
            service=audit.service,
            instance_id=audit.instance_id,
        )
    except ClearanceGrantError as exc:
        # well-formed but not applicable to current state (already expired, or a
        # reason shorter than the storage floor) → 422.
        raise UnprocessableError(str(exc)) from exc
    # ponytail: applied synchronously (storage self-audits CLEARANCE_REVOKED);
    # event_id is the grant id because AuditEmitter doesn't surface the audit
    # row id. Upgrade to the real audit row id if that ever changes.
    return WriteAccepted(
        subject=AuditSubject.CLEARANCE_REVOKED.value,
        event_id=row.id,
        applied=True,
        poll=f"/v1/clearance/grants/{grant_id}",
    )
