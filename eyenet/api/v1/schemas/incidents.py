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
    body: str | None = None  # the classified message text (None if the row is gone)
    group: str | None = None  # WHERE: the channel/group title
    group_id: UUID | None = None  # the group's id (for the feed's group filter)
    actor_id: UUID | None = None  # WHO: sender actor (for dossier click-through)
    actor_handle: str | None = None
    labels: list[str]
    scores: dict[str, float]
    model_version: str
    classified_at: datetime
    # Operator ground-truth correction, when one exists (the retraining signal).
    corrected_labels: list[str] | None = None
    corrected_by: str | None = None
    corrected_at: datetime | None = None


class IncidentLabelUpdate(ApiSchema):
    """Operator relabel of a classified message: the true label set + an audit reason."""

    labels: list[str] = Field(description="True taxonomy heads; empty = false positive.")
    reason: str | None = None


class IncidentLabelOut(ApiSchema):
    """A stored operator label correction."""

    message_id: UUID
    labels: list[str]
    reason: str | None
    decided_by: str
    decided_at: datetime


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
