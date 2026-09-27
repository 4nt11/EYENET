# SPDX-License-Identifier: AGPL-3.0-or-later
"""Incident API projections (API_PLAN §9.5) — the operator triage-feed wire shape."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from ._base import ApiSchema


class IncidentOut(ApiSchema):
    """One classified incident, as served on the triage feed."""

    message_id: UUID
    labels: list[str]
    scores: dict[str, float]
    model_version: str
    classified_at: datetime


class IncidentRuleOut(ApiSchema):
    """An operator-defined detection rule."""

    id: UUID
    name: str
    pattern: str
    label: str
    weight: int
    enabled: bool
    description: str | None
    created_by: str | None
    created_at: datetime


class IncidentRuleCreate(ApiSchema):
    """Create an operator detection rule (RE2 pattern -> taxonomy label)."""

    name: str = Field(min_length=1, max_length=64)
    pattern: str = Field(min_length=1, max_length=4096)
    label: str
    weight: int = 2
    enabled: bool = True
    description: str | None = None


class IncidentRuleUpdate(ApiSchema):
    """Patch a rule; every field optional (only provided fields change)."""

    pattern: str | None = Field(default=None, min_length=1, max_length=4096)
    label: str | None = None
    weight: int | None = None
    enabled: bool | None = None
    description: str | None = None


__all__ = ["IncidentOut", "IncidentRuleCreate", "IncidentRuleOut", "IncidentRuleUpdate"]
