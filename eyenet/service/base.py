"""`ServiceBase` — shared lifecycle for every EYENET service.

Concerns owned here (PLAN §10 Milestone 1):
  - bus connection (held, not opened — services receive a `Bus` and a
    `Storage`)
  - audit emit (`service.start`, `service.ready`, `service.stop`)
  - structured logging via structlog (configured by `init_telemetry`)
  - signal-driven shutdown — set up by `runner.run_service`

Subclasses override:
  - `name` — service name constant
  - `instance_id` — collector uses pinned formula; others can be `f"{name}_1"`
  - `on_subscribe()` — one-shot setup, register handlers on the bus
  - `tick()` — optional heartbeat (default no-op)
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod

from eyenet.bus.publisher import BusEnvelopePublisher
from eyenet.contracts.bus import Bus
from eyenet.contracts.enums import SystemLogLevel
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry import AuditEmitter, get_logger


class ServiceBase(ABC):
    """Lifecycle base for every EYENET service skeleton."""

    def __init__(
        self,
        *,
        bus: Bus,
        storage: BaseRepository,
    ) -> None:
        self._bus = bus
        self._storage = storage
        self._publisher = BusEnvelopePublisher(bus)
        self._stop = asyncio.Event()
        self._log = get_logger()
        self._audit: AuditEmitter | None = None  # set by runner once name known

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def instance_id(self) -> str: ...

    @property
    def bus(self) -> Bus:
        return self._bus

    @property
    def storage(self) -> BaseRepository:
        return self._storage

    @property
    def publisher(self) -> BusEnvelopePublisher:
        return self._publisher

    @property
    def audit(self) -> AuditEmitter:
        if self._audit is None:
            self._audit = AuditEmitter(
                self._publisher,
                self._storage,
                service=self.name,
                instance_id=self.instance_id,
            )
        return self._audit

    @abstractmethod
    async def on_subscribe(self) -> None:
        """Register bus subscriptions / open per-service resources."""

    async def tick(self) -> None:  # noqa: B027 — empty default is intentional
        """Optional periodic heartbeat. Default: no-op."""

    async def shutdown(self) -> None:
        """Signal the run loop to stop. Idempotent."""

        self._stop.set()

    @property
    def stop_event(self) -> asyncio.Event:
        return self._stop

    async def syslog(
        self,
        *,
        level: SystemLogLevel,
        event: str,
        message: str,
    ) -> None:
        await self._storage.append_syslog(
            level=level,
            service=self.name,
            instance_id=self.instance_id,
            event=event,
            message=message,
        )


__all__ = ["ServiceBase"]
