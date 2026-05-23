"""Base mixins for EYENET contracts.

`BusEnvelope` — every EYENET-emitted bus message embeds `schema_version`,
`emitted_at`, and a W3C `trace_context` (PLAN §8.2). The re-exported
BEHAVE-TEXT `Observation` is the one exception: its trace context is
propagated via NATS message headers because BEHAVE-TEXT owns the schema.

`DbRowBase` — UUIDv7 PK + ingest timestamp. Rows that need additional
timestamps (e.g. `*_at_source`) declare them on the concrete model.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from uuid_extensions import uuid7

SCHEMA_VERSION_MAJOR: int = 1
SCHEMA_VERSION_MINOR: int = 0
SCHEMA_VERSION: str = f"{SCHEMA_VERSION_MAJOR}.{SCHEMA_VERSION_MINOR}"


def _now_utc() -> datetime:
    return datetime.now(tz=UTC)


def _new_uuid7() -> UUID:
    return UUID(str(uuid7()))


class TraceContext(BaseModel):
    """W3C trace context propagated on every EYENET bus envelope (PLAN §8.2).

    Fields mirror the W3C Trace Context HTTP headers. `traceparent` is the
    full 55-char string; `tracestate` is the optional vendor list.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    traceparent: str = Field(
        description="W3C traceparent header value, 55 chars, version-format-id",
        min_length=55,
        max_length=55,
    )
    tracestate: str | None = Field(default=None, description="W3C tracestate header value")


class BusEnvelope(BaseModel):
    """Common fields for every EYENET-emitted bus message.

    `schema_version` is mandatory (PLAN §4.1). Major version compatibility is
    enforced by consumer-side validators; minor bumps remain wire-compatible.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default=SCHEMA_VERSION, description="major.minor")
    emitted_at: datetime = Field(default_factory=_now_utc)
    trace_context: TraceContext


class DbRowBase(BaseModel):
    """Base shape for persisted rows (UUIDv7 PK + ingest timestamp)."""

    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=_new_uuid7)


def canonical_json(model: BaseModel, exclude: set[str] | None = None) -> bytes:
    """Stable canonical JSON for hashing (audit chain, fingerprints).

    Sort keys, no whitespace, UTF-8. Excludes the chain-mutable fields by
    default at the call-site, not here.
    """

    data: dict[str, Any] = model.model_dump(mode="json", exclude=exclude or set())
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")


__all__ = [
    "SCHEMA_VERSION",
    "SCHEMA_VERSION_MAJOR",
    "SCHEMA_VERSION_MINOR",
    "BusEnvelope",
    "DbRowBase",
    "TraceContext",
    "canonical_json",
]
