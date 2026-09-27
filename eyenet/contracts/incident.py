"""Incident contract — the persisted twin of a multi-label classification result,
plus the bus subject the classifier service publishes fired incidents on.

`IncidentRow` mirrors `eyenet.models.incident.IncidentTable`. Append-only: one row per
(message, classification run). See development/incident-taxonomy.md and
eyenet/incidents/classifier.py.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from ._base import BusEnvelope, DbRowBase

INCIDENT_SUBJECT: str = "incident.detected"
"""Bus subject the classifier service publishes a fired incident on (operator triage
feed / SSE). Only messages with >=1 fired label are emitted; `none` is not published."""


class IncidentRow(DbRowBase):
    """Persisted multi-label classification result for one message."""

    message_id: UUID
    labels: list[str]
    scores: dict[str, float]
    model_version: str
    classified_at: datetime


class IncidentRuleRow(DbRowBase):
    """Operator-defined incident detection rule (persisted twin of IncidentRuleTable)."""

    name: str
    pattern: str
    label: str
    weight: int = 2
    enabled: bool = True
    description: str | None = None
    created_by: str | None = None
    created_at: datetime


class IncidentEnvelope(BusEnvelope):
    """Fired-incident bus event (published on INCIDENT_SUBJECT) — the triage feed payload.
    Carries the dereferenceable evidence_ref, not the body (operator-grade)."""

    message_id: UUID
    evidence_ref: str
    labels: list[str]
    scores: dict[str, float]
    model_version: str
    classified_at: datetime


__all__ = ["INCIDENT_SUBJECT", "IncidentEnvelope", "IncidentRow", "IncidentRuleRow"]
