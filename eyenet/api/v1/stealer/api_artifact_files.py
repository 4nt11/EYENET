# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/stealer/artifacts/{sha}/{folder}/files (read:stealer).

Backs the Files tab tree. Returns one row per file in the victim's
directory. FE builds the tree client-side by splitting rel_path on '/'.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path

from eyenet.api.deps import CurrentUser, RequireScope
from eyenet.api.v1.schemas.stealer import (
    StealerArtifactFileRow,
    StealerArtifactFilesResponse,
)
from eyenet.api.v1.stealer._artifacts import reader
from eyenet.stealer.query import StealerCorpusUninitializedError

router = APIRouter(tags=["stealer"])


@router.get(
    "/stealer/artifacts/{archive_sha256}/{victim_folder:path}/files",
    operation_id="stealer_artifact_files",
    response_model=StealerArtifactFilesResponse,
    status_code=200,
)
async def stealer_artifact_files(
    _: Annotated[CurrentUser, Depends(RequireScope("read:stealer"))],
    archive_sha256: Annotated[str, Path(min_length=64, max_length=64)],
    victim_folder: Annotated[str, Path(min_length=1, max_length=512)],
) -> StealerArtifactFilesResponse:
    try:
        rows = await reader.file_tree(archive_sha256, victim_folder)
    except StealerCorpusUninitializedError as exc:
        raise HTTPException(503, "stealer corpus not initialized yet") from exc
    return StealerArtifactFilesResponse(
        archive_sha256=archive_sha256,
        victim_folder=victim_folder,
        items=[
            StealerArtifactFileRow(
                rel_path=r.rel_path,
                filename=r.filename,
                size_bytes=r.size_bytes,
                heuristic_kind=r.heuristic_kind,
                extractor_touched=r.extractor_touched,
                rows_emitted=r.rows_emitted,
                sample_head=r.sample_head,
                file_sha256=r.file_sha256,
            )
            for r in rows
        ],
    )
