# SPDX-License-Identifier: AGPL-3.0-or-later
"""Schemas for the artifact browse surface (GET /v1/artifacts[/{id}/mentions]).

An artifact is deduped (one row per distinct value); the counts and the mention
list are read-time aggregates over the ``infrastructure_artifact_mention`` edge
joined to ``message`` — how many times a value appeared, by who, where, and when.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from eyenet.contracts.enums import ResolutionState

from ._base import ApiSchema
from .pagination import CursorPage


class ArtifactSummary(ApiSchema):
    """One deduped artifact with its mention aggregates (browse row)."""

    id: UUID
    kind: str
    value: str
    resolution_state: ResolutionState
    resolved_to_source_id: UUID | None = None
    first_seen_at_ingest: datetime
    last_seen_at_ingest: datetime
    mention_count: int = Field(ge=0, description="Messages this value appeared in.")
    distinct_actors: int = Field(ge=0, description="Distinct actors who mentioned it.")
    distinct_groups: int = Field(ge=0, description="Distinct groups it appeared in.")
    first_mention_at: datetime | None = None
    last_mention_at: datetime | None = None


class ArtifactMention(ApiSchema):
    """One sighting of an artifact — the who / where / when drill-down row."""

    message_id: UUID
    actor_id: UUID
    actor_handle: str | None = None
    actor_display_name: str | None = None
    group_id: UUID
    group_title: str | None = None
    source_id: UUID
    ts: datetime
    char_offset: int | None = None


class CursorPageArtifactSummary(CursorPage[ArtifactSummary]):
    pass


class CursorPageArtifactMention(CursorPage[ArtifactMention]):
    pass


__all__ = [
    "ArtifactMention",
    "ArtifactSummary",
    "CursorPageArtifactMention",
    "CursorPageArtifactSummary",
]
