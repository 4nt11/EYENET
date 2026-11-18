# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/stealer/audit/search -- case-insensitive substring search over the
corpus audit (read:stealer). Powers the Corpus Health search bar and the
later graph-explorer "does the corpus contain this entity" transform.

Searches across filename + rel_path + sample_head. The ngrambf_v1 skip index
on sample_head + tokenbf_v1 on rel_path prune granules that provably don't
contain the query substring, so a search over a million+ rows still returns
in sub-second. ``match_context`` returns ~200 chars centered on the first
hit inside sample_head so the FE can show the operator WHERE the string
lives in the audited file.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from eyenet.api.deps import CurrentUser, RequireScope
from eyenet.api.v1.schemas.stealer import (
    StealerAuditSearchResponse,
    StealerAuditSearchRow,
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
    "/stealer/audit/search",
    operation_id="stealer_audit_search",
    response_model=StealerAuditSearchResponse,
    status_code=200,
)
async def stealer_audit_search(
    _: Annotated[CurrentUser, Depends(RequireScope("read:stealer"))],
    q: Annotated[
        str,
        Query(
            min_length=2,
            max_length=200,
            description=(
                "Substring to search for (case-insensitive) across filename, "
                "rel_path, and sample_head. Minimum 2 characters so a lone "
                "wildcard can't force a full corpus scan."
            ),
        ),
    ],
    page: PageParam = 1,
    limit: LimitParam = 50,
) -> StealerAuditSearchResponse:
    try:
        rows, total, page_count = await reader.search(q=q, page=page, limit=limit)
    except StealerCorpusUninitializedError:
        return StealerAuditSearchResponse(
            initialized=False, items=[], page_meta=empty_meta(page, limit)
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"stealer corpus unavailable: {exc}") from exc
    return StealerAuditSearchResponse(
        items=[
            StealerAuditSearchRow(
                archive_sha256=r.archive_sha256,
                rel_path=r.rel_path,
                filename=r.filename,
                heuristic_kind=r.heuristic_kind,
                size_bytes=r.size_bytes,
                match_context=r.match_context,
            )
            for r in rows
        ],
        page_meta=built_meta(page, limit, total, page_count),
    )
