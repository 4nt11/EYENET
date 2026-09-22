# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/documents — the document triage list (M10 viewer).

Metadata-only page so the viewer table can self-populate. Authenticated but not
tier-scoped: rows carry metadata (filename/hash/tier), never bytes or extracted
text — those stay behind the clearance-gated manifest + signed /access step.
This is the operator-grade-evidence posture (§4.7): the operator sees WHAT
evidence exists; reading its content is separately gated and journaled.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from eyenet.api.deps import CurrentUser, get_current_user, get_storage
from eyenet.api.deps_paging import CursorParams, cursor_params
from eyenet.api.v1.schemas.documents import CursorPageDocumentSummary, DocumentSummary
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["documents"])


@router.get(
    "/documents",
    operation_id="documents_list",
    response_model=CursorPageDocumentSummary,
    status_code=200,
)
async def documents_list(
    _: Annotated[CurrentUser, Depends(get_current_user)],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    page: Annotated[CursorParams, Depends(cursor_params)],
    doc_kind: Annotated[str | None, Query()] = None,
    review_required: Annotated[bool | None, Query()] = None,
) -> CursorPageDocumentSummary:
    rows = await storage.list_documents(
        doc_kind=doc_kind,
        review_required=review_required,
        limit=page.fetch_limit,
        offset=page.offset,
    )
    estimated_total = (
        await storage.count_documents(doc_kind=doc_kind, review_required=review_required)
        if page.include_total
        else None
    )
    return CursorPageDocumentSummary(
        items=[DocumentSummary.from_domain(r) for r in rows[: page.limit]],
        next_cursor=page.next_cursor(fetched=len(rows)),
        estimated_total=estimated_total,
    )
