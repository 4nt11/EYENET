# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/stealer/audit/samples -- sample_head snippets for one filename (read:stealer).

Rule-authoring tool: operator picks a filename from the /audit/unknown workbench,
hits this endpoint, gets N representative sample_head snippets from different
archives so they can see the real shape of the file before writing a parser rule.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from eyenet.api.deps import CurrentUser, RequireScope
from eyenet.api.v1.schemas.stealer import (
    StealerAuditSampleRow,
    StealerAuditSamplesResponse,
)
from eyenet.api.v1.stealer._audit import PageParam, built_meta, empty_meta, reader
from eyenet.stealer.query import StealerCorpusUninitializedError

router = APIRouter(tags=["stealer"])


@router.get(
    "/stealer/audit/samples",
    operation_id="stealer_audit_samples",
    response_model=StealerAuditSamplesResponse,
    status_code=200,
)
async def stealer_audit_samples(
    _: Annotated[CurrentUser, Depends(RequireScope("read:stealer"))],
    filename: Annotated[
        str,
        Query(
            min_length=1,
            max_length=256,
            description="Case-insensitive exact match on the audit filename column.",
        ),
    ],
    page: PageParam = 1,
    # Smaller default limit than the other audit routes: each sample is up to
    # 2 KiB of text, and the operator typically only needs 5 to 10 side-by-side
    # to write a rule. FE dropdown here is [5, 10, 25].
    limit: Annotated[int, Query(ge=1, le=25)] = 5,
) -> StealerAuditSamplesResponse:
    try:
        rows, total, page_count = await asyncio.to_thread(
            lambda: reader.samples(filename=filename, page=page, limit=limit)
        )
    except StealerCorpusUninitializedError:
        return StealerAuditSamplesResponse(
            initialized=False, items=[], page_meta=empty_meta(page, limit)
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"stealer corpus unavailable: {exc}") from exc
    return StealerAuditSamplesResponse(
        items=[
            StealerAuditSampleRow(
                archive_sha256=r.archive_sha256,
                rel_path=r.rel_path,
                size_bytes=r.size_bytes,
                sample_head=r.sample_head,
            )
            for r in rows
        ],
        page_meta=built_meta(page, limit, total, page_count),
    )
