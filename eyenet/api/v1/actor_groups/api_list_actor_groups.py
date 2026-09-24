# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/actor-groups — crews: connected components of the shared-infra graph.

Clusters the ``shared_infra`` PROPOSED linkages (see the shared-infrastructure
linker) into crews and resolves each member's display label. This is the
operator-facing view of "who operates together" for templated-spam populations,
where stylometry cannot tell crews apart but shared infrastructure can.
"""

from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, get_storage
from eyenet.api.v1.schemas.actor_groups import (
    ActorGroupList,
    ActorGroupSummary,
    CrewLink,
    CrewMember,
)
from eyenet.api.v1.schemas.actors import actor_primary_handle
from eyenet.contracts.actor import ActorRow
from eyenet.contracts.attribution import LinkageRow
from eyenet.contracts.enums import LinkageState
from eyenet.linker.crews import build_crews
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["actor-groups"])

# Crews are computed in one in-memory pass over the shared_infra edges; the graph
# is small (operator scale). This caps the edge fetch.
_EDGE_LIMIT = 100_000


@router.get(
    "/actor-groups",
    operation_id="actor_groups_list",
    response_model=ActorGroupList,
    status_code=200,
)
async def actor_groups_list(
    _: Annotated[CurrentUser, Depends(RequireScope("read:actors"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
) -> ActorGroupList:
    links = cast(
        "list[LinkageRow]",
        await storage.list_linkages(
            state=LinkageState.PROPOSED, method="shared_infra", limit=_EDGE_LIMIT
        ),
    )
    edges = [
        (
            link.actor_a_id,
            link.actor_b_id,
            link.score,
            [str(v) for v in cast("list[object]", link.evidence.get("shared", []))],
        )
        for link in links
    ]
    crews = build_crews(edges)

    # TODO(evidence-messages): a drill-down that, per crew link, surfaces the actual
    # messages/posts from both actors carrying each shared indicator (the "here are
    # the posts" view). Needs a messages_with_indicator(actor_ids, token) query +
    # GET /v1/actor-groups/{crew_key}/evidence-messages. Deferred per operator.

    # Resolve labels for every member (bounded by crew membership — operator scale).
    member_ids: set[UUID] = {m for crew in crews for m in crew.members}
    labels: dict[UUID, str] = {}
    for aid in member_ids:
        actor = cast("ActorRow | None", await storage.get_actor(aid))
        labels[aid] = actor_primary_handle(actor) if actor is not None else f"id:{aid}"

    items = [
        ActorGroupSummary(
            size=len(crew.members),
            members=[CrewMember(actor_id=m, label=labels[m]) for m in crew.members],
            top_infra=list(crew.top_infra),
            edge_count=crew.edge_count,
            max_score=crew.max_score,
            links=[
                CrewLink(actor_a_id=a, actor_b_id=b, score=s, shared=list(shared))
                for a, b, s, shared in crew.links
            ],
        )
        for crew in crews
    ]
    return ActorGroupList(items=items, count=len(items))
