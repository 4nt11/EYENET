# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/stealer/audit/unknown -- next-rule-to-write workbench (read:stealer).

Groups the audit by (filename, heuristic_kind), filters to rows where the
extractor did NOT touch the file and the kind is NOT empty/binary. Ordered by
occurrence count desc, so the most common unparsed filenames surface first.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from eyenet.api.deps import CurrentUser, RequireScope
from eyenet.api.v1.schemas.stealer import (
    StealerAuditUnknownResponse,
    StealerAuditUnknownRow,
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
    "/stealer/audit/unknown",
    operation_id="stealer_audit_unknown",
    response_model=StealerAuditUnknownResponse,
    status_code=200,
)
async def stealer_audit_unknown(
    _: Annotated[CurrentUser, Depends(RequireScope("read:stealer"))],
    page: PageParam = 1,
    limit: LimitParam = 25,
) -> StealerAuditUnknownResponse:
    try:
        rows, total, page_count = await asyncio.to_thread(
            lambda: reader.unknown(page=page, limit=limit)
        )
    except StealerCorpusUninitializedError:
        return StealerAuditUnknownResponse(
            initialized=False, items=[], page_meta=empty_meta(page, limit)
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"stealer corpus unavailable: {exc}") from exc
    return StealerAuditUnknownResponse(
        items=[
            StealerAuditUnknownRow(
                filename=r.filename,
                heuristic_kind=r.heuristic_kind,
                occurrences=r.occurrences,
                archive_count=r.archive_count,
                sample_head=r.sample_head,
            )
            for r in rows
        ],
        page_meta=built_meta(page, limit, total, page_count),
    )
