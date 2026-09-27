# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/cases/{case_id}/attachments — case-scoped evidence attachments.

Direct-membership semantics (§4.10.1): returns only attachments explicitly
added to the case via ``case_member`` (``subject_kind=attachment``, not
removed) — NOT every attachment in storage. ``read:cases`` scope AND case
visibility are both required (a non-collaborator gets 404, no existence
oracle — see :func:`require_case_visible`).

The metadata-only projection mirrors ``GET /v1/attachments``; raw bytes still
sit behind the clearance-gated manifest + signed /access step (§5.6).
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, get_storage
from eyenet.api.deps_paging import CursorParams, cursor_params
from eyenet.api.v1.cases._detail import require_case_visible
from eyenet.api.v1.schemas.attachments import AttachmentSummary, CursorPageAttachmentSummary
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["cases"])


@router.get(
    "/cases/{case_id}/attachments",
    operation_id="cases_list_attachments",
    response_model=CursorPageAttachmentSummary,
    status_code=200,
)
async def cases_list_attachments(
    case_id: UUID,
    current_user: Annotated[CurrentUser, Depends(RequireScope("read:cases"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    page: Annotated[CursorParams, Depends(cursor_params)],
) -> CursorPageAttachmentSummary:
    await require_case_visible(storage, case_id, current_user)
    rows = await storage.list_attachments_for_case(
        case_id, limit=page.fetch_limit, offset=page.offset
    )
    estimated_total = (
        await storage.count_attachments_for_case(case_id) if page.include_total else None
    )
    return CursorPageAttachmentSummary(
        items=[AttachmentSummary.from_domain(r) for r in rows[: page.limit]],
        next_cursor=page.next_cursor(fetched=len(rows)),
        estimated_total=estimated_total,
    )
