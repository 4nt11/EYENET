# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/attachments — the attachment list (M10 viewer).

Metadata-only page (mirrors ``GET /v1/documents``): authenticated, all rows,
no bytes. The raw blob stays behind the clearance-gated manifest + signed
/access step (§5.6). Newest-first via ``id DESC`` (uuid7 is time-ordered).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from eyenet.api.deps import CurrentUser, get_current_user, get_storage
from eyenet.api.deps_paging import CursorParams, cursor_params
from eyenet.api.v1.schemas.attachments import AttachmentSummary, CursorPageAttachmentSummary
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["attachments"])


@router.get(
    "/attachments",
    operation_id="attachments_list",
    response_model=CursorPageAttachmentSummary,
    status_code=200,
)
async def attachments_list(
    _: Annotated[CurrentUser, Depends(get_current_user)],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    page: Annotated[CursorParams, Depends(cursor_params)],
    mime: Annotated[str | None, Query()] = None,
) -> CursorPageAttachmentSummary:
    rows = await storage.list_attachments(mime=mime, limit=page.fetch_limit, offset=page.offset)
    estimated_total = await storage.count_attachments(mime=mime) if page.include_total else None
    return CursorPageAttachmentSummary(
        items=[AttachmentSummary.from_domain(r) for r in rows[: page.limit]],
        next_cursor=page.next_cursor(fetched=len(rows)),
        estimated_total=estimated_total,
    )
