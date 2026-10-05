"""Global-search schemas — one hit per entity + a faceted cursor page.

GLOBAL_SEARCH.md §4. A `SearchHit` is a thin projection of `SearchDocumentTable`
(the derived index), NOT the canonical entity; the UI links each hit to its
real detail surface by `entity_type` + `entity_id`.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import Field

from eyenet.models.search import SearchDocumentTable

from ._base import ApiSchema
from .enums import EntityType
from .pagination import CursorPage


class SearchHit(ApiSchema):
    """One cross-entity search result row."""

    entity_type: EntityType
    entity_id: UUID
    source_id: UUID | None = None
    status: str | None = Field(
        default=None,
        description="Lifecycle facet within a type (group: candidate/joined/monitored/known).",
    )
    title: str
    subtitle: str | None = None

    @classmethod
    def from_domain(cls, doc: SearchDocumentTable) -> SearchHit:
        return cls(
            entity_type=EntityType(doc.entity_type),
            entity_id=doc.entity_id,
            source_id=doc.source_id,
            status=doc.status,
            title=doc.title,
            subtitle=doc.subtitle,
        )


class CursorPageSearchHit(CursorPage[SearchHit]):
    """A page of hits plus facet counts for the whole matching set."""

    by_type: dict[str, int] = Field(
        default_factory=dict,
        description="Count of matches per entity_type across the whole result set.",
    )
    by_source: dict[str, int] = Field(
        default_factory=dict,
        description="Count of matches per source_id ('' = no single source).",
    )


__all__ = ["CursorPageSearchHit", "SearchHit"]
