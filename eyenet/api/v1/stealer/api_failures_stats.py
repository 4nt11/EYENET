# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/stealer/failures/stats (read:stealer).

Corpus-wide tile numbers for the parse-failures workbench header:
coverage %, total/parsed counts, parse-miss files, shape buckets, and
hard gotractor crashes. All cheap aggregates against the pre-rolled
per-victim MV and file_audit; no WHERE filter plumbing on purpose so
the tiles always show the global picture, independent of the row-level
filters on the table below.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope
from eyenet.api.v1.schemas.stealer import StealerFailuresStats
from eyenet.stealer.query import StealerCorpusUninitializedError, StealerFailuresReader

router = APIRouter(tags=["stealer"])
_reader = StealerFailuresReader()


@router.get(
    "/stealer/failures/stats",
    operation_id="stealer_failures_stats",
    response_model=StealerFailuresStats,
    status_code=200,
)
async def stealer_failures_stats(
    _: Annotated[CurrentUser, Depends(RequireScope("read:stealer"))],
) -> StealerFailuresStats:
    try:
        s = await _reader.global_stats()
    except StealerCorpusUninitializedError:
        return StealerFailuresStats(initialized=False)
    return StealerFailuresStats(
        total_files=s.total_files,
        parsed_files=s.parsed_files,
        coverage_pct=s.coverage_pct,
        fail_files=s.fail_files,
        shape_buckets=s.shape_buckets,
        crash_files=s.crash_files,
    )
