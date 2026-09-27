"""IncidentTable — per-message multi-label incident classification result.

Append-only: one row per (message, classification run). Re-classifying a message
under a new model_version inserts a new row rather than mutating the old one, so the
classification history is preserved (operator-grade evidence) and the bulk writer stays
a plain ANSI insert (no dialect-specific upsert). The current verdict for a message is
the row with the latest classified_at.

`labels` is the fired multi-label set (model + prefilter cascade); `scores` is the
per-head calibrated probability for every taxonomy head. See
development/incident-taxonomy.md and eyenet/incidents/classifier.py.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON
from sqlmodel import Column, Field, SQLModel

from ._base import new_uuid7


class IncidentTable(SQLModel, table=True):
    __tablename__ = "incident"

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    message_id: UUID = Field(foreign_key="message.id", index=True)
    labels: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    scores: dict[str, float] = Field(default_factory=dict, sa_column=Column(JSON))
    model_version: str = Field(index=True)
    classified_at: datetime = Field(index=True)
