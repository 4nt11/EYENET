# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/stealer/failures (read:stealer).

Parse-failures workbench, shape-grouped. One row per character-class
fingerprint over file_audit.sample_head for files no gotractor rule
emitted records for. Backs the /tuning/stealer/failures workbench.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from eyenet.api.deps import CurrentUser, RequireScope
from eyenet.api.v1.schemas.stealer import (
    StealerFailureShape,
    StealerFailuresResponse,
)
from eyenet.api.v1.stealer._artifacts import (
    LimitParam,
    PageParam,
    built_meta,
    empty_meta,
)
from eyenet.stealer.query import StealerCorpusUninitializedError, StealerFailuresReader

router = APIRouter(tags=["stealer"])
_reader = StealerFailuresReader()


@router.get(
    "/stealer/failures",
    operation_id="stealer_failures_list",
    response_model=StealerFailuresResponse,
    status_code=200,
)
async def stealer_failures_list(
    _: Annotated[CurrentUser, Depends(RequireScope("read:stealer"))],
    page: PageParam = 1,
    limit: LimitParam = 25,
    filename: Annotated[str | None, Query(max_length=128)] = None,
    heuristic_kind: Annotated[str | None, Query(max_length=32)] = None,
) -> StealerFailuresResponse:
    try:
        rows, total, page_count = await _reader.list_shapes(
            page=page,
            limit=limit,
            filename=filename,
            heuristic_kind=heuristic_kind,
        )
    except StealerCorpusUninitializedError:
        return StealerFailuresResponse(
            initialized=False, items=[], page_meta=empty_meta(page, limit)
        )
    return StealerFailuresResponse(
        items=[
            StealerFailureShape(
                shape_sig=r.shape_sig,
                shape_preview=r.shape_preview,
                count=r.count,
                victims=r.victims,
                archives=r.archives,
                sample=r.sample,
                sample_archive_sha256=r.sample_archive_sha256,
                sample_victim_folder=r.sample_victim_folder,
                sample_file_path=r.sample_file_path,
                heuristic_kind=r.heuristic_kind,
                filenames=r.filenames,
            )
            for r in rows
        ],
        page_meta=built_meta(page, limit, total, page_count),
    )
