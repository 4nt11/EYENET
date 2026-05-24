"""GET /v1/audit/verify — hash-chain integrity check."""

from __future__ import annotations

from fastapi import APIRouter, Query

from eyenet.api.v1.schemas.audit import AuditVerifyResult

router = APIRouter(tags=["audit"])


@router.get(
    "/audit/verify",
    operation_id="audit_verify",
    response_model=AuditVerifyResult,
    status_code=200,
)
async def audit_verify(
    rows: int = Query(default=1000, ge=1, le=100_000),
) -> AuditVerifyResult:
    raise NotImplementedError("audit_verify (M9.0 skeleton)")
