"""Collector interface + the load-bearing `compute_instance_id` (PLAN §2.1).

PINNED: `instance_id = sha256(identity_name + "::" + source_kind).hexdigest()[:8]`

NO SALT. The same `(identity_name, source_kind)` MUST produce the same
`instance_id` on every operator workstation so audit trails correlate across
hosts. Two collector implementations diverging on this hash silently breaks
bus-subject filtering and OPSEC correlation — treat it as a load-bearing
constant. Asserted by `test_instance_id` against a fixed input/output pair.

Also home to :class:`CollectorRow` — the persisted shape returned from
the storage layer (M9.C3 / API_PLAN §4.11.1) — and :func:`redact_config`,
the pure helper that strips sensitive ``config`` keys for callers without
the ``read:collectors_config`` grant.
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ._base import DbRowBase
from .enums import (
    CollectorDesiredState,
    CollectorObservedState,
    CollectorState,
    SourceKind,
)


def compute_instance_id(identity_name: str, source_kind: SourceKind | str) -> str:
    """Compute the canonical 8-hex collector instance_id (PLAN §2.1).

    Stable across hosts; never includes the raw identity name in cleartext.
    """

    kind = source_kind.value if isinstance(source_kind, SourceKind) else source_kind
    digest = hashlib.sha256(f"{identity_name}::{kind}".encode()).hexdigest()
    return digest[:8]


class CollectorHealth(BaseModel):
    """Baseline `health()` response (PLAN §2.1). Required on every concrete collector."""

    model_config = ConfigDict(extra="forbid")

    state: CollectorState
    identity_name: str
    instance_id: str = Field(min_length=8, max_length=8)
    last_message_at: datetime | None = None
    messages_in_last_hour: int = 0
    current_subscriptions: list[str] = Field(default_factory=list)
    last_error: str | None = None


class CollectorBase(ABC):
    """Abstract collector. One process owns one identity (PLAN §2.1).

    `health()` is required from day one. Adding it later forces a retrofit on
    every concrete collector, so the cost is paid up front.
    """

    @property
    @abstractmethod
    def identity_name(self) -> str: ...

    @property
    @abstractmethod
    def source_kind(self) -> SourceKind: ...

    @property
    def instance_id(self) -> str:
        """Default impl uses the pinned formula. Subclasses MUST NOT override."""

        return compute_instance_id(self.identity_name, self.source_kind)

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    @abstractmethod
    async def health(self) -> CollectorHealth: ...


class CollectorFleetHealth(BaseModel):
    """Fleet snapshot for ``GET /v1/collectors/health`` (API_PLAN §3.9).

    Aggregate over every :class:`CollectorRow`; distinct from
    :class:`CollectorHealth` (a single live collector's self-report).
    """

    model_config = ConfigDict(extra="forbid")

    total: int = Field(ge=0)
    counts_by_observed_state: dict[CollectorObservedState, int] = Field(default_factory=dict)
    oldest_heartbeat_at: datetime | None = Field(
        default=None,
        description="Oldest last_heartbeat_at among non-STOPPED collectors; null if none.",
    )
    restart_storm_leader_id: UUID | None = Field(
        default=None, description="Collector with the highest restart_count, if > 0."
    )
    max_restart_count: int = Field(default=0, ge=0)


class CollectorRow(DbRowBase):
    """Persisted Collector row (API_PLAN §4.11.1, MODELS §2.19).

    The ``config`` blob is opaque at this layer; the API surface
    (M9.D2) validates it against the discriminated union and applies
    :func:`redact_config` for callers without
    ``read:collectors_config``. See API_PLAN §4.11.4 for the full
    sensitivity contract.
    """

    instance_name: str = Field(min_length=3, max_length=128)
    kind: SourceKind
    source_id: UUID
    identity_id: UUID
    config: dict[str, Any] = Field(default_factory=dict)
    desired_state: CollectorDesiredState = CollectorDesiredState.STOPPED
    observed_state: CollectorObservedState = CollectorObservedState.STOPPED
    restart_count: int = Field(default=0, ge=0)
    last_heartbeat_at: datetime | None = None
    last_error_type: str | None = Field(default=None, max_length=128)
    last_error_message: str | None = Field(default=None, max_length=4096)
    created_at: datetime
    created_by_user_id: UUID
    notes: str | None = Field(default=None, max_length=1024)


# Sentinel surfaced in the redacted shape so the UI can render the
# correct config widget even when it can't see the body. Stable wire
# string — part of the API_PLAN §4.11.4 contract.
_REDACTED_MARKER: dict[str, Any] = {"__redacted__": True}


def redact_config(
    config: dict[str, Any],
    *,
    has_read_grant: bool,
) -> dict[str, Any]:
    """Return ``config`` if the caller has ``read:collectors_config``, else
    a stub preserving only the ``kind`` discriminator (API_PLAN §4.11.4).

    Pure function — no I/O, no logging, no side effects. Suitable for
    use both in API response serialization and in audit payload
    construction (where the redacted form is what gets persisted).

    When the input lacks ``kind``, the output still carries
    ``__redacted__: True`` so a downstream consumer never confuses a
    malformed blob for a fully-readable one.
    """
    if has_read_grant:
        return config
    redacted: dict[str, Any] = dict(_REDACTED_MARKER)
    if "kind" in config:
        redacted["kind"] = config["kind"]
    return redacted


__all__ = [
    "CollectorBase",
    "CollectorFleetHealth",
    "CollectorHealth",
    "CollectorRow",
    "compute_instance_id",
    "redact_config",
]
