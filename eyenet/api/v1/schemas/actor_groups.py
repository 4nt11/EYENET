# SPDX-License-Identifier: AGPL-3.0-or-later
"""Actor-group (crew) schemas — connected components of the shared-infra graph.

A crew is a set of accounts that share operational infrastructure (contact
handles, wallets, t.me links). See ``eyenet.linker.crews`` for the clustering and
``development/linker-antispam-spec.md`` §3.

OpenAPI: ``contracts/openapi/eyenet.v1.yaml`` — ActorGroupSummary, CrewMember,
ActorGroupList.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import Field

from ._base import ApiSchema


class CrewMember(ApiSchema):
    """One account in a crew, with its display label resolved."""

    actor_id: UUID
    label: str = Field(max_length=256, description="@handle, else display name, else platform id")


class CrewLink(ApiSchema):
    """One pairwise shared_infra link inside a crew (the evidence behind edge_count)."""

    actor_a_id: UUID
    actor_b_id: UUID
    score: float = Field(ge=0.0, le=1.0)
    shared: list[str] = Field(default_factory=list, description="raw indicator tokens on this link")


class ActorGroupSummary(ApiSchema):
    """A crew: a connected component of shared-infrastructure links."""

    size: int = Field(ge=2, description="number of member accounts")
    members: list[CrewMember]
    top_infra: list[str] = Field(
        default_factory=list,
        description="most-frequently-shared operational indicators within the crew",
    )
    edge_count: int = Field(ge=1, description="shared_infra links inside the crew")
    max_score: float = Field(ge=0.0, le=1.0)
    links: list[CrewLink] = Field(
        default_factory=list, description="the pairwise links behind edge_count, strongest first"
    )


class ActorGroupList(ApiSchema):
    """200 response for GET /v1/actor-groups — all crews, largest first."""

    items: list[ActorGroupSummary]
    count: int = Field(ge=0)


class OpenCrewCaseRequest(ApiSchema):
    """Body for POST /v1/actor-groups/case — promote a crew to an investigation."""

    members: list[UUID] = Field(min_length=2, description="the crew's member actor ids")
    top_infra: list[str] = Field(
        default_factory=list, description="shared indicators (for title/key)"
    )
    title: str | None = Field(default=None, max_length=256)


class OpenCrewCaseResult(ApiSchema):
    """200 response for POST /v1/actor-groups/case."""

    case_id: UUID
    crew_key: str


class SweepCrewCasesRequest(ApiSchema):
    """Body for POST /v1/actor-groups/sweep-cases — auto-open big-crew cases."""

    min_size: int = Field(default=8, ge=2, description="auto-open crews with >= this many members")
    min_score: float = Field(default=0.8, ge=0.0, le=1.0, description="and max edge score >= this")


class SweepCrewCasesResult(ApiSchema):
    """202 response for POST /v1/actor-groups/sweep-cases."""

    opened: int = Field(ge=0, description="new cases opened this sweep")


__all__ = [
    "ActorGroupList",
    "ActorGroupSummary",
    "CrewLink",
    "CrewMember",
    "OpenCrewCaseRequest",
    "OpenCrewCaseResult",
    "SweepCrewCasesRequest",
    "SweepCrewCasesResult",
]
