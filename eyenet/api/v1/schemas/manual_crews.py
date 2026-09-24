# SPDX-License-Identifier: AGPL-3.0-or-later
"""Manual (operator-curated) crew schemas.

A manual crew is a persistent, hand-built actor group, distinct from the derived
/actor-groups crews. See ``eyenet.models.manual_crew``.

OpenAPI: ``contracts/openapi/eyenet.v1.yaml``.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field, model_validator

from ._base import ApiSchema


class CreateManualCrewRequest(ApiSchema):
    """Body for POST /v1/crews."""

    name: str = Field(min_length=1, max_length=256)
    notes: str | None = Field(default=None, max_length=4096)
    members: list[UUID] = Field(default_factory=list, description="optional seed member actor ids")


class CreateManualCrewResult(ApiSchema):
    """201 response for POST /v1/crews."""

    crew_id: UUID


class ManualCrewSummary(ApiSchema):
    """One manual crew in the list."""

    crew_id: UUID
    name: str = Field(max_length=256)
    notes: str | None = None
    member_count: int = Field(ge=0)
    updated_at: datetime


class ManualCrewList(ApiSchema):
    """200 response for GET /v1/crews."""

    items: list[ManualCrewSummary]
    count: int = Field(ge=0)


class ManualCrewMemberEntry(ApiSchema):
    """One member of a manual crew, label resolved."""

    actor_id: UUID
    handle: str | None = None
    display_name: str | None = None
    added_at: datetime


class ManualCrewDetail(ApiSchema):
    """200 response for GET /v1/crews/{id}."""

    crew_id: UUID
    name: str = Field(max_length=256)
    notes: str | None = None
    created_at: datetime
    updated_at: datetime
    members: list[ManualCrewMemberEntry] = Field(default_factory=list)


class AddCrewMemberRequest(ApiSchema):
    """Body for POST /v1/crews/{id}/members — by actor id or @handle."""

    actor_id: UUID | None = None
    handle: str | None = Field(default=None, max_length=256)

    @model_validator(mode="after")
    def _one_of(self) -> AddCrewMemberRequest:
        if (self.actor_id is None) == (self.handle is None):
            raise ValueError("provide exactly one of actor_id or handle")
        return self


__all__ = [
    "AddCrewMemberRequest",
    "CreateManualCrewRequest",
    "CreateManualCrewResult",
    "ManualCrewDetail",
    "ManualCrewList",
    "ManualCrewMemberEntry",
    "ManualCrewSummary",
]
