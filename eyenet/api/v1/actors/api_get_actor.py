# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/actors/{actor_id} — full actor detail (M9.F1)."""

from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, ResourceNotFound, get_storage
from eyenet.api.v1.schemas.actors import ActorDetail, AliasEntry
from eyenet.contracts.actor import ActorRow
from eyenet.contracts.attribution import PersonaRow
from eyenet.contracts.source import SourceRow
from eyenet.models.actor import ActorAliasHistoryTable
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["actors"])


@router.get(
    "/actors/{actor_id}",
    operation_id="actors_get",
    response_model=ActorDetail,
    status_code=200,
)
async def actors_get(
    actor_id: UUID,
    _: Annotated[CurrentUser, Depends(RequireScope("read:actors"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
) -> ActorDetail:
    actor = cast("ActorRow | None", await storage.get_actor(actor_id))
    if actor is None:
        raise ResourceNotFound("actor")
    persona = cast("PersonaRow | None", await storage.persona_for_actor(actor_id))
    observation_count = await storage.count_observations_for_actor(actor_id)
    source = cast("SourceRow | None", await storage.get_source(actor.source_id))
    alias_rows = cast("list[ActorAliasHistoryTable]", await storage.actor_aliases(actor_id))
    aliases = [AliasEntry.from_domain(r) for r in alias_rows]
    # An Actor belongs to exactly one Source; cross-platform identity is the
    # Persona's job. So `platforms` is the single source kind (or empty if the
    # source row is somehow absent).
    platforms = [source.kind.value] if source is not None else []
    return ActorDetail(
        actor_id=actor.id,
        primary_handle=actor.current_handle or actor.platform_userid,
        platforms=platforms,
        score=None,
        first_seen=actor.first_seen_at_source or actor.first_seen_at_ingest,
        last_seen=actor.last_seen_at_source or actor.last_seen_at_ingest,
        alias_count=len(aliases),
        aliases=aliases,
        observation_count=observation_count,
        persona_id=persona.id if persona is not None else None,
        assessment=actor.operator_assessment,
    )
