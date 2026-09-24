# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/relations/rebuild — operator-triggered actor-relation batch pass.

The API form of the mention/forward relation builder, so the frontend can rebuild
the actor_relation graph without the CLI. Runs synchronously in the request: one
in-memory pass over stored messages, fine at small-operator corpus size (same
posture as the anti-spam linker passes).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, get_storage
from eyenet.api.v1.schemas.relations import RebuildRelationsResult
from eyenet.relations.mentions import run_relation_builder
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["relations"])


@router.post(
    "/relations/rebuild",
    operation_id="relations_rebuild",
    response_model=RebuildRelationsResult,
    status_code=202,
)
async def relations_rebuild(
    _: Annotated[CurrentUser, Depends(RequireScope("write:linkage_decision"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
) -> RebuildRelationsResult:
    return RebuildRelationsResult(edges=await run_relation_builder(storage))
