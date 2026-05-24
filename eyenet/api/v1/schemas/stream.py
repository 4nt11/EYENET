"""SSE event payloads — wire shapes for `/v1/stream/*`.

These models describe the `data:` JSON of each Server-Sent Event. The
OpenAPI declares which subjects each stream may emit via the
`x-eyenet-sse-events` operation extension (§9.7); the codegen pipeline
follows the extension refs to produce typed TypeScript discriminated
unions for the UI's SSE handler.

`from_bus_envelope` constructors are deferred: bus events already carry
typed Pydantic models (subclasses of `BusEnvelope` in
`eyenet.contracts.*`); the SSE handler projects them directly when it
ships in M9.5.

OpenAPI: `contracts/openapi/eyenet.v1.yaml` — *Event, StreamGapEvent.
API_PLAN §3.5, §6, §9.7.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from ._base import ApiSchema
from .enums import LinkageState


class LinkageProposedEvent(ApiSchema):
    """`data:` payload for `event: linkage.proposed`."""

    event_id: UUID
    linkage_id: UUID
    actor_a_id: UUID
    actor_b_id: UUID
    score: float
    method: str = Field(max_length=64)
    ts: datetime


class LinkageStateChangedEvent(ApiSchema):
    """`data:` payload for `event: linkage.{confirmed,rejected,suspected}`."""

    event_id: UUID
    linkage_id: UUID
    state: LinkageState
    decided_by: UUID | None = None
    ts: datetime


class PersonaUpdatedEvent(ApiSchema):
    """`data:` payload for `event: persona.updated`."""

    event_id: UUID
    persona_id: UUID
    change: Literal["member_added", "member_removed", "label_changed", "created"]
    ts: datetime


class AuditEvent(ApiSchema):
    """`data:` payload for `event: <eyenet.audit.* last segment>`.

    Minimal projection — full forensic detail lives in the durable audit
    row reachable via `GET /v1/audit?subject=...`.
    """

    event_id: UUID
    subject: str = Field(max_length=128)
    user_id: UUID | None = None
    ts: datetime


class ControlEvent(ApiSchema):
    """`data:` payload for `event: <eyenet.control.* last segment>`."""

    event_id: UUID
    subject: str = Field(max_length=128)
    user_id: UUID | None = None
    reason: str | None = Field(default=None, max_length=512)
    ts: datetime


class StreamGapEvent(ApiSchema):
    """`event: stream.gap` — replay cursor predates oldest available.

    Emitted once before the handler resumes from the oldest available
    event. Clients decide whether to backfill via REST (API_PLAN §6.2).
    """

    oldest_available: str = Field(max_length=64)


__all__ = [
    "AuditEvent",
    "ControlEvent",
    "LinkageProposedEvent",
    "LinkageStateChangedEvent",
    "PersonaUpdatedEvent",
    "StreamGapEvent",
]
