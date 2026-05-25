"""`CollectorSkeleton` — boots, claims identity, subscribes to its control subject.

Concrete collectors (e.g. `TelegramCollectorStub` in M1, real telethon in M2)
inherit from this and override `produce()` to actually fetch messages.
M1 default: no production unless a fixture replay loop is wired.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from eyenet.contracts.bus import Bus
from eyenet.contracts.collector import (
    CollectorBase,
    CollectorHealth,
    compute_instance_id,
)
from eyenet.contracts.enums import CollectorState, SourceKind
from eyenet.contracts.identity_pool import IdentityPool
from eyenet.identity_pool.loader import IdentityFileEntry
from eyenet.service import ServiceBase
from eyenet.storage.repository import BaseRepository


class CollectorSkeleton(ServiceBase, CollectorBase):
    """Base skeleton for any collector."""

    def __init__(
        self,
        *,
        bus: Bus,
        storage: BaseRepository,
        pool: IdentityPool,
        identity_name: str,
        source_kind: SourceKind,
    ) -> None:
        super().__init__(bus=bus, storage=storage)
        self._pool = pool
        self._identity_name = identity_name
        self._source_kind = source_kind
        self._instance_id = compute_instance_id(identity_name, source_kind)
        self._claimed: IdentityFileEntry | None = None
        self._messages_in_last_hour = 0
        self._last_message_at: datetime | None = None

    @property
    def name(self) -> str:
        return f"collector.{self._source_kind.value}"

    @property
    def instance_id(self) -> str:
        return self._instance_id

    @property
    def identity_name(self) -> str:
        return self._identity_name

    @property
    def source_kind(self) -> SourceKind:
        return self._source_kind

    async def start(self) -> None:
        # Provided by CollectorBase ABC; runner.run_service drives lifecycle.
        # Concrete collectors override if they need imperative start logic.
        return None

    async def stop(self) -> None:
        await self.shutdown()

    async def health(self) -> CollectorHealth:
        return CollectorHealth(
            state=CollectorState.RUNNING if self._claimed else CollectorState.STARTING,
            identity_name=self._identity_name,
            instance_id=self._instance_id,
            last_message_at=self._last_message_at,
            messages_in_last_hour=self._messages_in_last_hour,
            current_subscriptions=[],
        )

    async def on_subscribe(self) -> None:
        self._claimed = cast("IdentityFileEntry", await self._pool.claim(self._identity_name))

    def _record_emission(self) -> None:
        self._last_message_at = datetime.now(tz=UTC)
        self._messages_in_last_hour += 1


__all__ = ["CollectorSkeleton"]
