# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/linker/run-infra and /v1/linker/detect-copypasta — operator-triggered
anti-spam batch passes (the API form of `eyenet link-infra` / `detect-copypasta`,
so the frontend can run them without the CLI).

Both run synchronously in the request — fine at small-operator corpus size; a
worker/queue is the upgrade if a corpus grows past a single fast pass.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, get_storage
from eyenet.api.v1.schemas.linker import DetectCopypastaResult, RunInfraResult
from eyenet.linker.infra_linker import run_infra_linker
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["linker"])


@router.post(
    "/linker/run-infra",
    operation_id="linker_run_infra",
    response_model=RunInfraResult,
    status_code=202,
)
async def linker_run_infra(
    _: Annotated[CurrentUser, Depends(RequireScope("write:linkage_decision"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
) -> RunInfraResult:
    return RunInfraResult(proposed=await run_infra_linker(storage))


@router.post(
    "/linker/detect-copypasta",
    operation_id="linker_detect_copypasta",
    response_model=DetectCopypastaResult,
    status_code=202,
)
async def linker_detect_copypasta(
    _: Annotated[CurrentUser, Depends(RequireScope("write:linkage_decision"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
) -> DetectCopypastaResult:
    return DetectCopypastaResult(flagged=await storage.detect_copypasta_templates())
