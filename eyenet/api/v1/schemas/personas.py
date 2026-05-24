"""Persona-resource schemas — summary, detail, member list.

OpenAPI: `contracts/openapi/eyenet.v1.yaml` — Persona*, PersonaMember.
API_PLAN §3.2.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from eyenet.models.persona import PersonaMembershipTable, PersonaTable

from ._base import ApiSchema
from .pagination import CursorPage


def _label_or_synthesized(persona: PersonaTable) -> str:
    """Domain stores `label: str | None`; the API contract requires non-null.

    When the domain label is unset we synthesize a deterministic placeholder
    from the persona id so the wire shape never leaks `None`. Operators who
    want a human-readable label set it via the persona-update path.
    """

    if persona.label:
        return persona.label
    return f"persona-{persona.id.hex[:8]}"


class PersonaSummary(ApiSchema):
    """Projection of MODELS.md §2.6 Persona for listing surfaces."""

    persona_id: UUID
    label: str = Field(max_length=256)
    member_count: int = Field(ge=0)

    @classmethod
    def from_domain(cls, persona: PersonaTable, member_count: int) -> PersonaSummary:
        """Member count is pre-computed by the route layer (count over
        `persona_membership`); the projector doesn't query storage."""

        return cls(
            persona_id=persona.id,
            label=_label_or_synthesized(persona),
            member_count=member_count,
        )


class PersonaDetail(PersonaSummary):
    """Projection of MODELS.md §2.6 Persona for `GET /v1/personas/{id}`."""

    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, persona: PersonaTable, member_count: int) -> PersonaDetail:
        return cls(
            persona_id=persona.id,
            label=_label_or_synthesized(persona),
            member_count=member_count,
            created_at=persona.created_at,
            updated_at=persona.updated_at,
        )


class PersonaMember(ApiSchema):
    """Projection of MODELS.md §2.6a PersonaMembership."""

    actor_id: UUID
    since: datetime
    via_linkage_id: UUID | None = None

    @classmethod
    def from_domain(cls, membership: PersonaMembershipTable) -> PersonaMember:
        return cls(
            actor_id=membership.actor_id,
            since=membership.joined_at,
            via_linkage_id=membership.via_linkage_id,
        )


class CursorPagePersonaMember(CursorPage[PersonaMember]):
    """200 page response for `GET /v1/personas/{id}/members`."""


__all__ = [
    "CursorPagePersonaMember",
    "PersonaDetail",
    "PersonaMember",
    "PersonaSummary",
]
