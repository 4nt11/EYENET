# SPDX-License-Identifier: AGPL-3.0-or-later
"""SearchDocumentTable — one denormalized haystack row per entity (GLOBAL_SEARCH.md).

A DERIVED, rebuildable index maintained by the SearchIndexer service: NOT a
source of truth. Lives in the main store alongside the operational tables (like
``message_fts``), with backend-specific full-text indexes applied as raw DDL
(SQLite FTS5 over ``haystack``/``handles``; Postgres ``tsvector`` GIN + ``pg_trgm``
GIN) that are fenced out of Alembic autogenerate.

`entity_type` / `status` are plain strings (the enum ``.value``), not SQLAlchemy
Enum columns, to avoid a native Postgres ENUM type and CHECK-constraint churn on
a table that is cheap to drop and rebuild.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

from ._base import new_uuid7


class SearchDocumentTable(SQLModel, table=True):
    __tablename__ = "search_document"
    __table_args__ = (
        UniqueConstraint("entity_type", "entity_id", name="uq_search_document_entity"),
    )

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    # EntityType.value (actor/group/thread/message/...). Plain str on purpose.
    entity_type: str = Field(index=True)
    # The source row's id (actor.id, group_.id, message.id, ...).
    entity_id: UUID = Field(index=True)
    # Owning source/platform, when the entity has exactly one. NULL for
    # cross-source entities (persona, crew, case).
    source_id: UUID | None = Field(default=None, index=True)
    # Lifecycle facet within a type (group: candidate/joined/monitored/known;
    # linkage/case status; ...). NULL when the type has no lifecycle.
    status: str | None = Field(default=None, index=True)
    # Display label + secondary line for the result row.
    title: str = Field(default="")
    subtitle: str | None = None
    # ALL searchable prose for this entity, concatenated (the FTS/tsvector body).
    haystack: str = Field(default="")
    # Identifiers (handles, aliases, t.me, wallets) for substring/trigram match.
    handles: str | None = None
    updated_at: datetime


__all__ = ["SearchDocumentTable"]
