# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/stealer/artifacts/{sha}/{folder}/records (read:stealer).

Backs the Credentials / System / Audit / Files-details tabs' record
lists. Supports filter by rule_id or family.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from eyenet.api.deps import CurrentUser, RequireScope
from eyenet.api.v1.schemas.stealer import (
    StealerArtifactRecordRow,
    StealerArtifactRecordsResponse,
)
from eyenet.api.v1.stealer._artifacts import (
    LimitParam,
    PageParam,
    built_meta,
    reader,
)
from eyenet.stealer.query import StealerCorpusUninitializedError

router = APIRouter(tags=["stealer"])


@router.get(
    "/stealer/artifacts/{archive_sha256}/{victim_folder:path}/records",
    operation_id="stealer_artifact_records",
    response_model=StealerArtifactRecordsResponse,
    status_code=200,
)
async def stealer_artifact_records(
    _: Annotated[CurrentUser, Depends(RequireScope("read:stealer"))],
    archive_sha256: Annotated[str, Path(min_length=64, max_length=64)],
    victim_folder: Annotated[str, Path(min_length=1, max_length=512)],
    page: PageParam = 1,
    limit: LimitParam = 50,
    rule_id: Annotated[str | None, Query(max_length=128)] = None,
    family: Annotated[str | None, Query(max_length=64)] = None,
    category: Annotated[str | None, Query(max_length=32)] = None,
) -> StealerArtifactRecordsResponse:
    try:
        rows, total, page_count = await reader.records(
            archive_sha256,
            victim_folder,
            page=page,
            limit=limit,
            rule_id=rule_id,
            family=family,
            category=category,
        )
    except StealerCorpusUninitializedError as exc:
        raise HTTPException(503, "stealer corpus not initialized yet") from exc
    return StealerArtifactRecordsResponse(
        archive_sha256=archive_sha256,
        victim_folder=victim_folder,
        items=[
            StealerArtifactRecordRow(
                rule_id=r.rule_id,
                family=r.family,
                file_path=r.file_path,
                fields=r.fields,
            )
            for r in rows
        ],
        page_meta=built_meta(page, limit, total, page_count),
    )
