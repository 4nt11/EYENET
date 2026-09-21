"""Event-log row DTO (API_PLAN §11.5, MODELS §2.29).

Storage-return shape for the per-transition event logs. Lives in ``contracts``
so both the storage ABC and the concrete mixins can reference it without the
ABC depending on the concrete layer. Never crosses the bus.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class EventLogRow:
    parent_id: UUID
    event_seq: int
    event_subject: str
    event_id: UUID
    ts: datetime
    traceparent: str
    tracestate: str | None
    actor: str | None
    payload_digest: str | None


__all__ = ["EventLogRow"]
