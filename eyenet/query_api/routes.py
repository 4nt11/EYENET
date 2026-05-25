"""Read-only query API route definitions.

All endpoints are GET. No writes — operator decisions are CLI-only (audited).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, cast
from uuid import UUID  # noqa: TC003

from fastapi import APIRouter, Depends, HTTPException, Query

from eyenet.storage.repository import BaseRepository

if TYPE_CHECKING:
    from eyenet.contracts.attribution import LinkageRow, PersonaRow, ProfileRow

from .deps import get_storage
from .models import (
    ActorSummary,
    GraphStats,
    HealthResponse,
    LinkageSummary,
    NeighborEdge,
    PersonaSummary,
)

router = APIRouter()

StorageDep = Annotated[BaseRepository, Depends(get_storage)]


def _profile_to_summary(profile: ProfileRow, persona_id: UUID | None) -> ActorSummary:
    return ActorSummary(
        actor_id=profile.actor_id,
        role_signal=profile.role_signal,
        role_confidence=profile.role_confidence,
        profile_version=profile.version,
        derived_at=profile.derived_at,
        persona_id=persona_id,
    )


def _linkage_to_summary(row: LinkageRow) -> LinkageSummary:
    return LinkageSummary(
        linkage_id=row.id,
        actor_a_id=row.actor_a_id,
        actor_b_id=row.actor_b_id,
        state=row.state.value,
        method=row.method,
        score=row.score,
        proposed_at=row.proposed_at,
        decided_at=row.decided_at,
        decided_by=row.decided_by,
    )


@router.get("/healthz", response_model=HealthResponse)
async def healthz() -> HealthResponse:
    return HealthResponse()


@router.get("/actor/{actor_id}", response_model=ActorSummary)
async def get_actor(actor_id: UUID, storage: StorageDep) -> ActorSummary:
    profile_raw = await storage.get_current_profile(actor_id)
    if profile_raw is None:
        raise HTTPException(status_code=404, detail="actor not found")
    profile = cast("ProfileRow", profile_raw)
    persona_raw = await storage.persona_for_actor(actor_id)
    persona_id = cast("PersonaRow", persona_raw).id if persona_raw is not None else None
    return _profile_to_summary(profile, persona_id)


@router.get("/actor/{actor_id}/neighbors", response_model=list[NeighborEdge])
async def get_actor_neighbors(
    actor_id: UUID,
    storage: StorageDep,
    edge_type: str | None = Query(default=None),
    state: str | None = Query(default=None),
) -> list[NeighborEdge]:
    edges = await storage.graph_neighbors(actor_id, edge_type=edge_type)
    result = [
        NeighborEdge(neighbor_id=nid, edge_type=etype, attrs=attrs) for nid, etype, attrs in edges
    ]
    if state is not None:
        result = [e for e in result if e.attrs.get("state") == state]
    return result


@router.get("/persona/{persona_id}", response_model=PersonaSummary)
async def get_persona(persona_id: UUID, storage: StorageDep) -> PersonaSummary:
    persona_raw = await storage.get_persona(persona_id)
    if persona_raw is None:
        raise HTTPException(status_code=404, detail="persona not found")
    persona = cast("PersonaRow", persona_raw)
    member_actors: list[ActorSummary] = []
    for actor_id in persona.member_actor_ids:
        profile_raw = await storage.get_current_profile(actor_id)
        if profile_raw is not None:
            member_actors.append(_profile_to_summary(cast("ProfileRow", profile_raw), persona_id))
        else:
            member_actors.append(ActorSummary(actor_id=actor_id, persona_id=persona_id))
    return PersonaSummary(
        persona_id=persona.id,
        member_count=len(persona.member_actor_ids),
        member_actors=member_actors,
        created_at=persona.created_at,
        updated_at=persona.updated_at,
    )


@router.get("/linkages", response_model=list[LinkageSummary])
async def list_linkages(
    storage: StorageDep,
    actor_id: UUID | None = Query(default=None),  # noqa: B008
    state: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[LinkageSummary]:
    rows = await storage.list_linkages(
        actor_id=actor_id, state=state, limit=limit, offset=offset
    )
    return [_linkage_to_summary(cast("LinkageRow", r)) for r in rows]


@router.get("/graph/stats", response_model=GraphStats)
async def graph_stats(storage: StorageDep) -> GraphStats:
    counts = await storage.graph_stats()
    return GraphStats(**counts)


__all__ = ["router"]
