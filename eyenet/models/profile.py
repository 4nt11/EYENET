"""ProfileTable — see contracts/attribution.py.

Partial unique index on `actor_id WHERE is_current` enforces one current
row per actor.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, Index, text
from sqlmodel import Column, Field, SQLModel

from ._base import new_uuid7


class ProfileTable(SQLModel, table=True):
    __tablename__ = "profile"
    __table_args__ = (
        Index(
            "ix_profile_one_current_per_actor",
            "actor_id",
            unique=True,
            sqlite_where=text("is_current = 1"),
        ),
        Index("ix_profile_actor_version", "actor_id", "version"),
    )

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    # Cross-store reference (actor lives in messages.db) — indexed UUID, no FK.
    actor_id: UUID = Field(index=True)
    version: int
    is_current: bool = Field(default=False)
    role_signal: str | None = Field(default=None, index=True)
    role_confidence: float
    stylometric_summary: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    lexical_summary: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    temporal_summary: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    interaction_summary: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    network_summary: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    content_summary: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    derived_at: datetime
    derived_from_observation_count: int


__all__ = ["ProfileTable"]
