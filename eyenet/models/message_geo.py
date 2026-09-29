"""MessageGeoTable — victim-country attribution for an incident-flagged message.

A SIDECAR to the append-only ``incident`` table (mirrors ``incident_label``): the geo
engine runs only on messages the incident classifier flagged, and writes ONE verdict
per message here rather than a column on ``incident`` — a new table is created cleanly
by ``create_all`` with no wipe, whereas a new column on an existing table is not (there
are no migrations; CLAUDE.md §pre-public).

``country`` is the resolved ISO 3166-1 alpha-2 (like ``message.body_lang``, a bare
str by convention, not an enum), or NULL when the verdict is ``mixed``/``unknown``.
``status`` and ``decided_by`` carry the engine's provenance. ``engine_version`` lets a
future engine bump be detected and recomputed. See eyenet/classifier/geo.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlmodel import Field, SQLModel

from ._base import new_uuid7


class MessageGeoTable(SQLModel, table=True):
    __tablename__ = "message_geo"

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    message_id: UUID = Field(foreign_key="message.id", index=True, unique=True)
    country: str | None = None  # ISO 3166-1 alpha-2; NULL when mixed/unknown
    status: str  # "resolved" | "mixed" | "unknown"
    decided_by: str | None = None  # winning check kind, e.g. "country_name"
    engine_version: str = Field(index=True)
    classified_at: datetime
