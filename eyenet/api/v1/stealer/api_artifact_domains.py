# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/stealer/artifacts/{sha}/{folder}/domains (read:stealer).

Backs the EXTRACTED INDICATORS section of the drawer's SELECTED panel.
One row per (domain, source_kind) with aggregated count. Reads from the
stealer.victim_domains micro-MV so the query is sub-ms regardless of
the full corpus size.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path

from eyenet.api.deps import CurrentUser, RequireScope
from eyenet.api.v1.schemas.stealer import (
    StealerArtifactDomainRow,
    StealerArtifactDomainsResponse,
)
from eyenet.api.v1.stealer._artifacts import reader
from eyenet.stealer.query import StealerCorpusUninitializedError

router = APIRouter(tags=["stealer"])


@router.get(
    "/stealer/artifacts/{archive_sha256}/{victim_folder:path}/domains",
    operation_id="stealer_artifact_domains",
    response_model=StealerArtifactDomainsResponse,
    status_code=200,
)
async def stealer_artifact_domains(
    _: Annotated[CurrentUser, Depends(RequireScope("read:stealer"))],
    archive_sha256: Annotated[str, Path(min_length=64, max_length=64)],
    victim_folder: Annotated[str, Path(min_length=1, max_length=512)],
) -> StealerArtifactDomainsResponse:
    try:
        rows = await asyncio.to_thread(
            lambda: reader.domains(archive_sha256, victim_folder)
        )
    except StealerCorpusUninitializedError as exc:
        raise HTTPException(503, "stealer corpus not initialized yet") from exc
    return StealerArtifactDomainsResponse(
        archive_sha256=archive_sha256,
        victim_folder=victim_folder,
        items=[
            StealerArtifactDomainRow(
                domain=r.domain, source_kind=r.source_kind, count=r.count
            )
            for r in rows
        ],
    )
