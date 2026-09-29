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

# Canonical surface-gate name (bus modules export a SUBJECT* constant).
SUBJECT: str = INCIDENT_SUBJECT


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


class IncidentLabelRow(DbRowBase):
    """Operator ground-truth label correction for a message (twin of IncidentLabelTable).

    ``labels`` is the operator-asserted TRUE label set (may be empty = false positive).
    Distinct from IncidentRow, which is the model's immutable prediction."""

    message_id: UUID
    labels: list[str]
    reason: str | None = None
    decided_by: str
    decided_at: datetime


class MessageGeoRow(DbRowBase):
    """Victim-country attribution for a message (twin of MessageGeoTable).

    ``country`` is the resolved ISO 3166-1 alpha-2, or None when ``status`` is
    ``mixed``/``unknown``. Written by the geo-attribution service for incident-flagged
    messages only. See eyenet/classifier/geo."""

    message_id: UUID
    country: str | None = None
    status: str
    decided_by: str | None = None
    engine_version: str
    classified_at: datetime


class ThreadSummaryRow(DbRowBase):
    """Per-forum-thread rollup anchored on the OP (twin of ThreadSummaryTable).

    ``victim_country`` is the OP's ISO alpha-2 verdict (None if mixed/unknown);
    ``op_sent_at`` is the thread date. Incident labels are joined live off
    ``op_message_id``, not carried here. See eyenet/classifier/geo."""

    group_id: UUID
    op_message_id: UUID
    op_sent_at: datetime
    victim_country: str | None = None
    victim_status: str
    engine_version: str
    computed_at: datetime


class IncidentEnvelope(BusEnvelope):
    """Fired-incident bus event (published on INCIDENT_SUBJECT) — the triage feed payload.
    Carries the dereferenceable evidence_ref, not the body (operator-grade)."""

    message_id: UUID
    evidence_ref: str
    labels: list[str]
    scores: dict[str, float]
    model_version: str
    classified_at: datetime


__all__ = [
    "INCIDENT_SUBJECT",
    "SUBJECT",
    "IncidentEnvelope",
    "IncidentRow",
    "IncidentRuleRow",
    "MessageGeoRow",
    "ThreadSummaryRow",
]
