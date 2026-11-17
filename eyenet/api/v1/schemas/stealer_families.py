"""Pydantic schemas for the stealer-families CRUD surface."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class FamilyReference(BaseModel):
    title: str
    url: str


class StealerFamilyIn(BaseModel):
    model_config = ConfigDict(extra="allow")

    slug: str = Field(min_length=2, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    name: str = Field(min_length=1, max_length=120)
    status: Literal["active", "retired", "dormant", "new", "suspected"]
    first_seen_year: int | None = None
    aliases: list[str] | None = None
    signature_files: list[str] | None = None
    loaders: list[str] | None = None
    distribution_channels: list[str] | None = None
    references: list[FamilyReference] | None = None
    notes: str | None = None


class StealerFamilyOut(StealerFamilyIn):
    pass


class StealerFamilyListOut(BaseModel):
    families: list[StealerFamilyOut]
    total: int
