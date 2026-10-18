# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/artifacts/{artifact_id} - one deduped artifact with its mention aggregates
(dossier for the graph inspector). Same ArtifactSummary shape as the browse list row."""

from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, ResourceNotFound, get_storage
from eyenet.api.v1.schemas.artifacts import ArtifactSummary
from eyenet.contracts.infrastructure import InfrastructureArtifactRow
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["artifacts"])


@router.get(
    "/artifacts/{artifact_id}",
    operation_id="artifacts_get",
    response_model=ArtifactSummary,
    status_code=200,
)
async def artifacts_get(
    artifact_id: UUID,
    _: Annotated[CurrentUser, Depends(RequireScope("read:search"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
) -> ArtifactSummary:
    row = await storage.get_infrastructure_artifact_summary(artifact_id)
    if row is None:
        raise ResourceNotFound("artifact")
    art, mentions, actors, groups, first_ts, last_ts = cast(
        "tuple[InfrastructureArtifactRow, int, int, int, object, object]", row
    )
    return ArtifactSummary(
        id=art.id,
        kind=art.kind,
        value=art.value,
        resolution_state=art.resolution_state,
        resolved_to_source_id=art.resolved_to_source_id,
        first_seen_at_ingest=art.first_seen_at_ingest,
        last_seen_at_ingest=art.last_seen_at_ingest,
        mention_count=mentions,
        distinct_actors=actors,
        distinct_groups=groups,
        first_mention_at=first_ts,  # type: ignore[arg-type]
        last_mention_at=last_ts,  # type: ignore[arg-type]
    )
