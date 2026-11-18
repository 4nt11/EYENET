# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/stealer/families/counts (read:stealer).

Per-family victim count across the current verdict table. Used by the
families landing page to rank families by observed corpus share. Cheap
GROUP BY against victim_family_verdict FINAL; one row per distinct slug
including the empty-slug "no-verdict" bucket.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope
from eyenet.api.v1.schemas.stealer import StealerFamilyCount, StealerFamilyCountsResponse
from eyenet.stealer.query import StealerCorpusUninitializedError
from eyenet.stealer.query_family_counts import family_counts

router = APIRouter(tags=["stealer"])


@router.get(
    "/stealer/families/counts",
    operation_id="stealer_family_counts",
    response_model=StealerFamilyCountsResponse,
    status_code=200,
)
async def stealer_family_counts(
    _: Annotated[CurrentUser, Depends(RequireScope("read:stealer"))],
) -> StealerFamilyCountsResponse:
    try:
        rows = await family_counts()
    except StealerCorpusUninitializedError:
        return StealerFamilyCountsResponse(initialized=False, items=[])
    return StealerFamilyCountsResponse(
        items=[StealerFamilyCount(slug=slug, count=count) for slug, count in rows],
    )
