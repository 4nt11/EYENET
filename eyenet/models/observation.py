"""ObservationTable — see contracts/observation.py.

Hot-path index `(actor_id, primitive_name, observed_at DESC)` lives here.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON, Index
from sqlmodel import Column, Field, SQLModel

from eyenet.contracts.enums import ValueKind

from ._base import new_uuid7


class ObservationTable(SQLModel, table=True):
    __tablename__ = "observation"
    __table_args__ = (
        Index(
            "ix_observation_actor_primitive_observed",
            "actor_id",
            "primitive_name",
            "observed_at",
        ),
    )

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    # Cross-store reference (actor lives in messages.db) — indexed UUID, no FK.
    actor_id: UUID = Field(index=True)
    evidence_ref: str | None = Field(default=None, index=True)
    primitive_namespace: str = Field(index=True)
    primitive_name: str
    primitive_version: str
    value_kind: ValueKind
    value_hash: str | None = Field(default=None, index=True)
    value_numeric: float | None = None
    value_enum: str | None = None
    value_array: list[str] | None = Field(default=None, sa_column=Column(JSON))
    value_array_numeric: list[float] | None = Field(default=None, sa_column=Column(JSON))
    window_start: datetime | None = None
    window_end: datetime | None = None
    observed_at: datetime
    sensor_instance: str


__all__ = ["ObservationTable"]
