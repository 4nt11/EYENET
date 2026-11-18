# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/stealer/failures/{shape_sig}/samples (read:stealer).

Raw sample rows inside one parse-failure shape bucket. Drives the
workbench's row-expand (sample preview + trace-back) and the
"Draft rule from file" pre-fill flow.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from eyenet.api.deps import CurrentUser, RequireScope
from eyenet.api.v1.schemas.stealer import (
    StealerFailureSampleRow,
    StealerFailureSamplesResponse,
)
from eyenet.stealer.query import StealerCorpusUninitializedError, StealerFailuresReader

router = APIRouter(tags=["stealer"])
_reader = StealerFailuresReader()


@router.get(
    "/stealer/failures/{shape_sig:path}/samples",
    operation_id="stealer_failure_samples",
    response_model=StealerFailureSamplesResponse,
    status_code=200,
)
async def stealer_failure_samples(
    _: Annotated[CurrentUser, Depends(RequireScope("read:stealer"))],
    shape_sig: Annotated[str, Path(min_length=1, max_length=512)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> StealerFailureSamplesResponse:
    try:
        rows = await _reader.shape_samples(shape_sig, limit=limit)
    except StealerCorpusUninitializedError as exc:
        raise HTTPException(503, "stealer corpus not initialized yet") from exc
    return StealerFailureSamplesResponse(
        shape_sig=shape_sig,
        items=[
            StealerFailureSampleRow(
                archive_sha256=r.archive_sha256,
                victim_folder=r.victim_folder,
                file_path=r.file_path,
                filename=r.filename,
                size_bytes=r.size_bytes,
                sample_head=r.sample_head,
                heuristic_kind=r.heuristic_kind,
            )
            for r in rows
        ],
    )
