# SPDX-License-Identifier: AGPL-3.0-or-later
"""Incident API projections (API_PLAN §9.5) — the operator triage-feed wire shape."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from ._base import ApiSchema


class IncidentOut(ApiSchema):
    """One classified incident, as served on the triage feed."""

    message_id: UUID
    labels: list[str]
    scores: dict[str, float]
    model_version: str
    classified_at: datetime


__all__ = ["IncidentOut"]
