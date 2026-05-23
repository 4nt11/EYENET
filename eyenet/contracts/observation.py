"""Observation contract.

PLAN §4.1: BEHAVE-TEXT is the source of truth. We re-export
`behave_text.spec.Observation` as `ObservationEnvelope` and define our
own `ObservationRow` (the persisted twin, MODELS §2.3) without redefining the
wire shape.

Bus subject template: `actor.observation.text.{primitive_namespace}` (PLAN §3).
The BEHAVE-TEXT helper `event_topic_for(primitive)` produces the per-primitive
subject; we use the namespace prefix here for queue-group fanout.

Surface: bus+db. We export `SUBJECT_PREFIX` because the per-primitive subject
is parameterized; `subject_for(...)` is the single render function.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from behave_text.spec import (
    TOPIC_PREFIX,
    Observation as ObservationEnvelope,
    event_topic_for,
)
from pydantic import Field

from ._base import DbRowBase
from .enums import ValueKind

SUBJECT: str = "actor.observation.text.>"
"""Subscription pattern (NATS wildcard) for all text observations.

Concrete per-primitive subjects come from `subject_for_primitive(primitive)`.
The wildcard subject is the canonical entry the build-gate checks against
PLAN §3's `actor.observation.text.{primitive_namespace}` taxonomy.
"""


def subject_for_primitive(primitive: str) -> str:
    """Render the per-primitive bus subject (delegates to BEHAVE-TEXT)."""

    rendered: str = event_topic_for(primitive)
    return rendered


class ObservationRow(DbRowBase):
    """Persisted observation (MODELS §2.3).

    Indexed on `(actor_id, primitive_name, observed_at DESC)`. The hot path
    is "give me the most recent N observations of primitive X for actor Y."
    """

    actor_id: UUID
    evidence_ref: str | None = Field(
        default=None,
        description="message that produced it; null for window-aggregate observations",
    )
    primitive_namespace: str
    primitive_name: str
    primitive_version: str
    value_kind: ValueKind
    value_hash: str | None = None
    value_numeric: float | None = None
    value_enum: str | None = None
    value_array: list[str] | None = None
    value_array_numeric: list[float] | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None
    observed_at: datetime
    sensor_instance: str


__all__ = [
    "SUBJECT",
    "TOPIC_PREFIX",
    "ObservationEnvelope",
    "ObservationRow",
    "subject_for_primitive",
]
