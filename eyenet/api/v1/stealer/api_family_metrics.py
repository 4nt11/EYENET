# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/stealer/families/metrics (read:stealer).

Per-family precision/recall vs operator override ground truth. Backs the
tuning dashboard. See
development/STEALER_FAMILY_CLASSIFIER_DESIGN.md.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, get_storage
from eyenet.api.v1.schemas.stealer import StealerFamilyMetric, StealerFamilyMetricsResponse
from eyenet.stealer.query import StealerCorpusUninitializedError
from eyenet.stealer.query_family_metrics import family_metrics
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["stealer"])


@router.get(
    "/stealer/families/metrics",
    operation_id="stealer_family_metrics",
    response_model=StealerFamilyMetricsResponse,
    status_code=200,
)
async def stealer_family_metrics(
    _: Annotated[CurrentUser, Depends(RequireScope("read:stealer"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
) -> StealerFamilyMetricsResponse:
    try:
        rows = await family_metrics(storage)
    except StealerCorpusUninitializedError:
        return StealerFamilyMetricsResponse(initialized=False, items=[])
    return StealerFamilyMetricsResponse(
        items=[
            StealerFamilyMetric(
                slug=m.slug,
                tp=m.tp,
                fp=m.fp,
                fn=m.fn,
                precision=m.precision,
                recall=m.recall,
                override_count=m.override_count,
            )
            for m in rows
        ],
    )
