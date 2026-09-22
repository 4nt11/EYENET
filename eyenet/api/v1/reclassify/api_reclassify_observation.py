# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/observations/{observation_id}/reclassify — §4.9 promotion.

Promote-only. Requires an active ``admin:reclassify`` grant AND a valid operator
Ed25519 signature over the §5.7 canonical (see ``_reclassify_canonical``); a JWT
alone never authorises. Observations carry no content blob, so the signature
binds ``content_hash=""`` (the subject id is bound via the URL path). Storage is
the monotone authority and self-audits the promotion; every refusal lands a
``reclassify.rejected`` audit row.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from eyenet.api.deps import CurrentUser, RequireScope, get_audit, get_storage
from eyenet.api.v1.reclassify._common import perform_reclassify
from eyenet.api.v1.schemas.reclassify import ReclassificationRequest, ReclassificationResult
from eyenet.contracts.enums import ClearanceScope, ReclassificationSubjectKind
from eyenet.storage.reclassify import ReclassifyOutcome
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["reclassify"])


@router.post(
    "/observations/{observation_id}/reclassify",
    operation_id="observations_reclassify",
    response_model=ReclassificationResult,
    status_code=200,
)
async def observations_reclassify(
    observation_id: UUID,
    body: ReclassificationRequest,
    request: Request,
    current_user: Annotated[
        CurrentUser, Depends(RequireScope(ClearanceScope.ADMIN_RECLASSIFY.value))
    ],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
) -> ReclassificationResult:
    # No pre-fetch: observations carry no content hash to bind, and storage raises
    # a not-found ValueError that perform_reclassify maps to 404.
    async def _do(
        *, grant_id: UUID, operator_signature_pubkey_fingerprint: str
    ) -> ReclassifyOutcome:
        return await storage.reclassify_observation(
            observation_id=observation_id,
            new_tier=body.new_tier,
            operator_user_id=current_user.user_id,
            reason=body.reason,
            grant_id=grant_id,
            operator_signature_pubkey_fingerprint=operator_signature_pubkey_fingerprint,
            viewing_context=body.viewing_context,
            case_refs=body.case_refs,
            service=audit.service,
            instance_id=audit.instance_id,
        )

    return await perform_reclassify(
        subject_kind=ReclassificationSubjectKind.OBSERVATION,
        subject_id=observation_id,
        content_hash="",
        body=body,
        request=request,
        current_user=current_user,
        storage=storage,
        audit=audit,
        do_reclassify=_do,
    )
