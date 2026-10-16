# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/graph/expand/counts — per-enrichment neighbour totals (degree preview).

Feeds the enrichment menu so the operator sees ``messages (1,240)`` before
expanding. See ``development/GRAPH_EXPLORER.md`` §6.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from eyenet.api.deps import CurrentUser, RequireScope, UnprocessableError, get_storage
from eyenet.api.v1._clearance import enforce_entity_tier_clearance
from eyenet.api.v1.schemas.search import GraphExpandCounts
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["graph"])


@router.get(
    "/graph/expand/counts",
    operation_id="graph_expand_counts",
    response_model=GraphExpandCounts,
    status_code=200,
)
async def graph_expand_counts(
    current_user: Annotated[CurrentUser, Depends(RequireScope("read:search"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    node_type: Annotated[
        str, Query(alias="type", min_length=1, max_length=32, description="source entity_type")
    ],
    node_id: Annotated[UUID, Query(alias="id", description="source entity_id")],
) -> GraphExpandCounts:
    await enforce_entity_tier_clearance(storage, current_user, node_type, node_id)
    try:
        counts = await storage.graph_expand_counts(src_type=node_type, src_id=node_id)
    except ValueError as exc:
        raise UnprocessableError(str(exc)) from exc
    return GraphExpandCounts(counts=counts)
