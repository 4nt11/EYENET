# SPDX-License-Identifier: AGPL-3.0-or-later
"""Entity-change events that drive global-search reindexing (GLOBAL_SEARCH.md).

Emitted ONLY when an entity's searchable content actually changed (created or a
searchable field differs) — NOT on every upsert — so a busy group/actor does not
re-emit on every message (change-gated, §2.4). The ``SearchIndexer`` subscribes
to ``entity.>`` and reindexes the one entity named in the envelope.

Carries a pointer (type + id), never payload. Subjects: ``entity.<type>.changed``.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import Field

from ._base import BusEnvelope

SUBJECT_ENTITY_PREFIX: str = "entity."
SUBJECT_ACTOR_CHANGED: str = "entity.actor.changed"
SUBJECT_GROUP_CHANGED: str = "entity.group.changed"
SUBJECT_CASE_CHANGED: str = "entity.case.changed"


def entity_subject(entity_type: str) -> str:
    """Render the bus subject for an entity-change event."""
    return f"entity.{entity_type}.changed"


class EntityChangedEnvelope(BusEnvelope):
    """One entity row's searchable content changed; reindex it."""

    entity_type: str = Field(description="EntityType.value: actor | group | case | ...")
    entity_id: UUID = Field(description="PK of the changed row")
    source_id: UUID | None = Field(default=None, description="owning source, when single")


__all__ = [
    "SUBJECT_ACTOR_CHANGED",
    "SUBJECT_CASE_CHANGED",
    "SUBJECT_ENTITY_PREFIX",
    "SUBJECT_GROUP_CHANGED",
    "EntityChangedEnvelope",
    "entity_subject",
]
