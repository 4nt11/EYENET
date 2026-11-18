"""Pydantic schemas for the stealer-families CRUD surface."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class FamilyReference(BaseModel):
    title: str
    url: str


class StealerFamilyIn(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    slug: str = Field(min_length=2, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    name: str = Field(min_length=1, max_length=120)
    status: Literal["active", "retired", "dormant", "new", "suspected"]
    kind: Literal["stealer", "content", "tool", "combolist", "leak_pack"]
    schema_: int | None = Field(default=None, alias="schema")
    first_seen_year: int | None = None
    aliases: list[str] | None = None
    signature_files: list[str] | None = None
    loaders: list[str] | None = None
    distribution_channels: list[str] | None = None
    references: list[FamilyReference] | None = None
    notes: str | None = None
    # Classifier signals (Phase 2). Optional per-family; only populated for
    # kind=stealer entries in practice. See
    # development/STEALER_FAMILY_CLASSIFIER_DESIGN.md.
    signature_paths: list[str] | None = None
    signature_rule_ids: list[str] | None = None
    build_tag_regex: str | None = None
    antisignature_files: list[str] | None = None
    antisignature_rule_ids: list[str] | None = None
    confidence_floor: float | None = Field(default=None, ge=0.0, le=1.0)
    signal_weights: dict[str, float] | None = None


class StealerFamilyOut(StealerFamilyIn):
    pass


class StealerFamilyListOut(BaseModel):
    families: list[StealerFamilyOut]
    total: int
