# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/stealer/audit/coverage -- per-archive parse scorecard (read:stealer).

One row per archive_sha256 with total/parsed/unknown counts + pct_parsed.
Powers the Corpus Health dashboard "did we actually read every archive"
column.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from eyenet.api.deps import CurrentUser, RequireScope
from eyenet.api.v1.schemas.stealer import (
    StealerAuditCoverageResponse,
    StealerAuditCoverageRow,
)
from eyenet.api.v1.stealer._audit import (
    LimitParam,
    PageParam,
    built_meta,
    empty_meta,
    reader,
)
from eyenet.stealer.query import StealerCorpusUninitializedError

router = APIRouter(tags=["stealer"])


@router.get(
    "/stealer/audit/coverage",
    operation_id="stealer_audit_coverage",
    response_model=StealerAuditCoverageResponse,
    status_code=200,
)
async def stealer_audit_coverage(
    _: Annotated[CurrentUser, Depends(RequireScope("read:stealer"))],
    page: PageParam = 1,
    limit: LimitParam = 25,
) -> StealerAuditCoverageResponse:
    try:
        rows, total, page_count = await reader.coverage(page=page, limit=limit)
    except StealerCorpusUninitializedError:
        return StealerAuditCoverageResponse(
            initialized=False, items=[], page_meta=empty_meta(page, limit)
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"stealer corpus unavailable: {exc}") from exc
    return StealerAuditCoverageResponse(
        items=[
            StealerAuditCoverageRow(
                archive_sha256=r.archive_sha256,
                total_files=r.total_files,
                parsed_files=r.parsed_files,
                unknown_files=r.unknown_files,
                pct_parsed=r.pct_parsed,
                first_seen_at=r.first_seen_at,
            )
            for r in rows
        ],
        page_meta=built_meta(page, limit, total, page_count),
    )
