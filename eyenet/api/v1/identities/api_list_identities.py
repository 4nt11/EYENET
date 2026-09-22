# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/identities — list the identity pool.

The pool is small (small-operator scope) and ``list_identities`` returns the
full filtered set, so we paginate by slicing. Gated by ``read:collectors``:
identities are collector infrastructure, and no separate ``read:identity``
scope exists. OPSEC fields never cross the wire (see IdentitySummary).
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from eyenet.api.deps import CurrentUser, RequireScope, get_storage
from eyenet.api.deps_paging import CursorParams, cursor_params
from eyenet.api.v1.schemas.identities import CursorPageIdentitySummary, IdentitySummary
from eyenet.contracts.enums import IdentityRole, IdentityState
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["identities"])


@router.get(
    "/identities",
    operation_id="identities_list",
    response_model=CursorPageIdentitySummary,
    status_code=200,
)
async def identities_list(
    _: Annotated[CurrentUser, Depends(RequireScope("read:collectors"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    page: Annotated[CursorParams, Depends(cursor_params)],
    source_id: Annotated[UUID | None, Query()] = None,
    role: Annotated[IdentityRole | None, Query()] = None,
    state: Annotated[IdentityState | None, Query()] = None,
) -> CursorPageIdentitySummary:
    rows = await storage.list_identities(source_id=source_id, role=role, state=state)
    window = rows[page.offset : page.offset + page.fetch_limit]
    return CursorPageIdentitySummary(
        items=[IdentitySummary.from_domain(r) for r in window[: page.limit]],
        next_cursor=page.next_cursor(fetched=len(window)),
        estimated_total=len(rows) if page.include_total else None,
    )
