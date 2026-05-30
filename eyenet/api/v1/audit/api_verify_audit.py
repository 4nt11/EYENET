# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/audit/verify — hash-chain integrity check (M9.F4)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, get_storage
from eyenet.api.v1.schemas.audit import AuditChainBreak, AuditVerifyResult
from eyenet.contracts.audit import GENESIS_PREV_HASH, compute_self_hash, verify_chain
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["audit"])


@router.get(
    "/audit/verify",
    operation_id="audit_verify",
    response_model=AuditVerifyResult,
    status_code=200,
)
async def audit_verify(
    _: Annotated[CurrentUser, Depends(RequireScope("read:audit"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
) -> AuditVerifyResult:
    rows = await storage.all_audit()
    ok, idx = verify_chain(rows)
    first_break: AuditChainBreak | None = None
    if not ok and idx is not None:
        broken = rows[idx]
        recomputed = compute_self_hash(broken)
        if broken.self_hash != recomputed:
            # the row's own content was tampered with
            expected, actual = recomputed, broken.self_hash
        else:
            # the link to the previous row is broken
            expected = rows[idx - 1].self_hash if idx > 0 else GENESIS_PREV_HASH
            actual = broken.prev_hash
        first_break = AuditChainBreak(
            event_id=broken.id, expected_hash=expected, actual_hash=actual
        )
    return AuditVerifyResult(verified=ok, rows_checked=len(rows), first_break=first_break)
