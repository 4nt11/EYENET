"""Actor-resource schemas — summaries, details, neighbors, observations, timeline.

The discriminated-union `NeighborEdge` is the §9.3 typed-edge pattern that
replaces the old `dict[str, object]` attrs blob.

OpenAPI: `contracts/openapi/eyenet.v1.yaml` — Actor*, NeighborList, NeighborEdge,
LinkedTo*, BelongsToPersona*, ObservationSummary, TimelineEntry.
API_PLAN §3.2, §9.3.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from eyenet.contracts.enums import ValueKind
from eyenet.models.graph import GraphEdgeTable, GraphEdgeType
from eyenet.models.message import MessageTable
from eyenet.models.observation import ObservationTable

from ._base import ApiSchema
from .enums import LinkageState, SensitivityTier
from .pagination import CursorPage


class ActorSummary(ApiSchema):
    """Projection of MODELS.md §2.1 Actor for listing surfaces.

    TODO(M9.3): `from_domain(ActorTable, aliases: Sequence[ActorAliasHistoryTable])`.
    `primary_handle` derivation is policy-dependent — `current_handle` is a
    fast-path on the row, but the latest HANDLE alias may differ. The route
    layer owns the alias-join and policy choice; the projector takes the
    already-resolved string. Same constraint applies to `platforms`, which
    needs a cross-store source lookup.
    """

    actor_id: UUID
    primary_handle: str = Field(max_length=256)
    platforms: list[str] = Field(
        default_factory=list,
        description=(
            "Source platforms this actor has been observed on (e.g. ['telegram', 'matrix'])."
        ),
    )
    score: float | None = None


class ActorDetail(ActorSummary):
    """Projection of MODELS.md §2.1 Actor for `GET /v1/actors/{id}`.

    TODO(M9.3): `from_domain(ActorTable, aliases, observation_count, persona_id)`.
    Same alias-policy and cross-store concerns as ActorSummary.
    """

    first_seen: datetime
    last_seen: datetime
    alias_count: int = Field(ge=0)
    observation_count: int = Field(ge=0)
    persona_id: UUID | None = None


class LinkedToAttrs(ApiSchema):
    """Edge attributes on a `linked_to` neighbor edge."""

    state: LinkageState
    method: str = Field(max_length=64)
    score: float
    linkage_id: UUID


class BelongsToPersonaAttrs(ApiSchema):
    """Edge attributes on a `belongs_to_persona` neighbor edge."""

    since: datetime
    via_linkage_id: UUID | None = None


class LinkedToEdge(ApiSchema):
    """Projection of MODELS.md §2.10 GraphEdge with edge_type=LINKED_TO."""

    edge_type: Literal["linked_to"] = "linked_to"
    target_id: UUID
    attrs: LinkedToAttrs

    @classmethod
    def from_domain(cls, edge: GraphEdgeTable) -> LinkedToEdge:
        """Build from a `GraphEdgeTable` row whose `edge_type == LINKED_TO`.

        `attrs` on the domain row is `dict[str, Any]`; we project the four
        known keys (state, method, score, linkage_id) and reject malformed
        payloads via `extra="forbid"` on `LinkedToAttrs`.
        """

        if edge.edge_type is not GraphEdgeType.LINKED_TO:
            raise ValueError(f"expected LINKED_TO, got {edge.edge_type}")
        return cls(
            target_id=edge.dst_id,
            attrs=LinkedToAttrs.model_validate(edge.attrs),
        )


class BelongsToPersonaEdge(ApiSchema):
    """Projection of MODELS.md §2.10 GraphEdge with edge_type=BELONGS_TO_PERSONA."""

    edge_type: Literal["belongs_to_persona"] = "belongs_to_persona"
    target_id: UUID
    attrs: BelongsToPersonaAttrs

    @classmethod
    def from_domain(cls, edge: GraphEdgeTable) -> BelongsToPersonaEdge:
        if edge.edge_type is not GraphEdgeType.BELONGS_TO_PERSONA:
            raise ValueError(f"expected BELONGS_TO_PERSONA, got {edge.edge_type}")
        return cls(
            target_id=edge.dst_id,
            attrs=BelongsToPersonaAttrs.model_validate(edge.attrs),
        )


NeighborEdge = Annotated[
    LinkedToEdge | BelongsToPersonaEdge,
    Field(discriminator="edge_type"),
]


class NeighborList(ApiSchema):
    """200 response for `GET /v1/actors/{id}/neighbors` — typed-edge page."""

    items: list[NeighborEdge]
    next_cursor: str | None = None
    estimated_total: int | None = Field(default=None, ge=0)


class ObservationSummary(ApiSchema):
    """Projection of MODELS.md §2.4 Observation.

    Surfaces `sensitivity` (API_PLAN §4.7) so clients can render redaction
    state. Defaults to `NORMAL` from `from_domain` until M9.1 storage adds
    the `sensitivity` column to `ObservationTable`; document with TODO.
    """

    observation_id: UUID
    kind: str = Field(max_length=64)
    ts: datetime
    score: float | None = None
    primitive: str | None = Field(default=None, max_length=64)
    sensitivity: SensitivityTier = Field(
        description="Required scopes are derived from this — see API_PLAN §4.7.",
    )
    attachment_blob_id: UUID | None = Field(
        default=None,
        description="Present when this observation has a binary attachment.",
    )

    @classmethod
    def from_domain(cls, obs: ObservationTable) -> ObservationSummary:
        # TODO(M9.1): pull `sensitivity` from `obs.sensitivity` once the storage
        # column lands. Until then every projected row is conservatively `NORMAL`
        # at the API boundary; the handler layer must promote any row whose
        # primitive_namespace is on the sensitive-namespace list (M9.3).
        return cls(
            observation_id=obs.id,
            kind=f"{obs.primitive_namespace}:{obs.primitive_name}",
            ts=obs.observed_at,
            score=obs.value_numeric if obs.value_kind is ValueKind.NUMERIC else None,
            primitive=obs.primitive_name,
            sensitivity=SensitivityTier.NORMAL,
            attachment_blob_id=None,
        )


class TimelineEntry(ApiSchema):
    """Entry in `GET /v1/actors/{id}/timeline` — message or observation."""

    ts: datetime
    kind: Literal["message", "observation"]
    id: UUID
    summary: str | None = Field(default=None, max_length=512)

    @classmethod
    def from_message(cls, msg: MessageTable) -> TimelineEntry:
        body = msg.body
        return cls(
            ts=msg.sent_at_source,
            kind="message",
            id=msg.id,
            summary=body[:512] if body else None,
        )

    @classmethod
    def from_observation(cls, obs: ObservationTable) -> TimelineEntry:
        return cls(
            ts=obs.observed_at,
            kind="observation",
            id=obs.id,
            summary=f"{obs.primitive_namespace}:{obs.primitive_name}",
        )


class CursorPageObservationSummary(CursorPage[ObservationSummary]):
    """200 page response for `GET /v1/actors/{id}/observations`."""


class CursorPageTimelineEntry(CursorPage[TimelineEntry]):
    """200 page response for `GET /v1/actors/{id}/timeline`."""


class CursorPageActorSummary(CursorPage[ActorSummary]):
    """200 page response for `GET /v1/graph/search`."""


__all__ = [
    "ActorDetail",
    "ActorSummary",
    "BelongsToPersonaAttrs",
    "BelongsToPersonaEdge",
    "CursorPageActorSummary",
    "CursorPageObservationSummary",
    "CursorPageTimelineEntry",
    "LinkedToAttrs",
    "LinkedToEdge",
    "NeighborEdge",
    "NeighborList",
    "ObservationSummary",
    "TimelineEntry",
]
