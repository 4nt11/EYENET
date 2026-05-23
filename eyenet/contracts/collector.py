"""Collector interface + the load-bearing `compute_instance_id` (PLAN §2.1).

PINNED: `instance_id = sha256(identity_name + "::" + source_kind).hexdigest()[:8]`

NO SALT. The same `(identity_name, source_kind)` MUST produce the same
`instance_id` on every operator workstation so audit trails correlate across
hosts. Two collector implementations diverging on this hash silently breaks
bus-subject filtering and OPSEC correlation — treat it as a load-bearing
constant. Asserted by `test_instance_id` against a fixed input/output pair.
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from .enums import CollectorState, SourceKind


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


__all__ = ["CollectorBase", "CollectorHealth", "compute_instance_id"]
