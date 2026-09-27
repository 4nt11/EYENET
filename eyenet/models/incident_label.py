"""IncidentLabelTable — operator ground-truth correction for a classified message.

The classifier's own output lives in the append-only ``incident`` table and is NEVER
mutated: it is evidence of what the model predicted. This table is the SEPARATE operator
truth channel. One current correction per message (``message_id`` unique, upserted): the
operator says "the true label set for this message is X" — where X may be empty (a false
positive: the model fired but nothing is actually here). The pair (model prediction, operator
truth) is the retraining signal. See development/incident-taxonomy.md.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON
from sqlmodel import Column, Field, SQLModel

from ._base import new_uuid7


class IncidentLabelTable(SQLModel, table=True):
    __tablename__ = "incident_label"

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    message_id: UUID = Field(foreign_key="message.id", index=True, unique=True)
    labels: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    reason: str | None = None
    decided_by: str
    decided_at: datetime
