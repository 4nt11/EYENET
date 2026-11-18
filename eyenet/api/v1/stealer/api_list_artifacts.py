# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/stealer/artifacts -- per-victim card list (read:stealer).

Backs the artifacts left panel. One row per (archive_sha256, victim_folder)
with the compact card payload. Filter axes: country, traffic_affid,
has_wallet, has_corporate.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from eyenet.api.deps import CurrentUser, RequireScope
from eyenet.api.v1.schemas.stealer import (
    StealerArtifactCard,
    StealerArtifactsResponse,
)
from eyenet.api.v1.stealer._artifacts import (
    LimitParam,
    PageParam,
    built_meta,
    empty_meta,
    reader,
)
from eyenet.stealer.query import StealerCorpusUninitializedError

router = APIRouter(tags=["stealer"])


@router.get(
    "/stealer/artifacts",
    operation_id="stealer_list_artifacts",
    response_model=StealerArtifactsResponse,
    status_code=200,
)
async def stealer_list_artifacts(
    _: Annotated[CurrentUser, Depends(RequireScope("read:stealer"))],
    page: PageParam = 1,
    limit: LimitParam = 25,
    country: Annotated[str | None, Query(max_length=8)] = None,
    traffic_affid: Annotated[str | None, Query(max_length=64)] = None,
    has_wallet: Annotated[bool | None, Query()] = None,
    has_corporate: Annotated[bool | None, Query()] = None,
) -> StealerArtifactsResponse:
    try:
        rows, total, page_count = await reader.list_cards(
            page=page,
            limit=limit,
            country=country,
            traffic_affid=traffic_affid,
            has_wallet=has_wallet,
            has_corporate=has_corporate,
        )
    except StealerCorpusUninitializedError:
        return StealerArtifactsResponse(
            initialized=False, items=[], page_meta=empty_meta(page, limit)
        )
    return StealerArtifactsResponse(
        items=[
            StealerArtifactCard(
                archive_sha256=r.archive_sha256,
                victim_folder=r.victim_folder,
                country=r.country,
                traffic_affid=r.traffic_affid,
                build_version=r.build_version,
                creds_count=r.creds_count,
                cookies_count=r.cookies_count,
                wallet_vaults_count=r.wallet_vaults_count,
                has_corporate_marker=r.has_corporate_marker,
                has_wallet=r.has_wallet,
                has_crypter_banner=r.has_crypter_banner,
            )
            for r in rows
        ],
        page_meta=built_meta(page, limit, total, page_count),
    )
