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


class ActorGroupList(ApiSchema):
    """200 response for GET /v1/actor-groups — all crews, largest first."""

    items: list[ActorGroupSummary]
    count: int = Field(ge=0)


__all__ = ["ActorGroupList", "ActorGroupSummary", "CrewMember"]
