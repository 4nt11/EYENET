# SPDX-License-Identifier: AGPL-3.0-or-later
"""GeoAttributionService — victim-country attribution for incident-flagged messages.

Purely tick-driven, no bus subscription: each tick pulls a batch of incident-flagged
messages that have no geo verdict yet, runs the deterministic geo engine
(:mod:`eyenet.classifier.geo`) over each message body plus its thread title, and persists
the verdicts to the ``message_geo`` sidecar. The tick doubles as the backfill — it drains
the pre-existing corpus over successive ticks, then stays live as new incidents land.

Scope by design: only messages the incident classifier flagged, not the whole corpus.
The engine is pure and fast (~ms/message), so batches run inline on the tick.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from eyenet.classifier.geo import ENGINE_VERSION, classify_country
from eyenet.contracts.enums import SystemLogLevel
from eyenet.contracts.incident import MessageGeoRow
from eyenet.service import ServiceBase

if TYPE_CHECKING:
    from eyenet.contracts.bus import Bus
    from eyenet.storage.repository import BaseRepository

_DEFAULT_BATCH = 500


class GeoAttributionService(ServiceBase):
    """Attributes a victim country to each incident-flagged message (tick-driven)."""

    def __init__(
        self, *, bus: Bus, storage: BaseRepository, batch_size: int = _DEFAULT_BATCH
    ) -> None:
        super().__init__(bus=bus, storage=storage)
        self._batch_size = batch_size

    @property
    def name(self) -> str:
        return "geo_attribution"

    @property
    def instance_id(self) -> str:
        return "geo_default"

    async def on_subscribe(self) -> None:
        """No bus subscription — purely tick-driven."""

    async def tick(self) -> None:
        await self.attribute_batch()

    async def attribute_batch(self) -> int:
        """Classify one batch of un-attributed incident messages. Returns how many."""
        pending = await self.storage.messages_needing_geo(limit=self._batch_size)
        if not pending:
            return 0
        now = datetime.now(tz=UTC)
        rows: list[object] = []
        for message_id, body, title in pending:
            verdict = classify_country(body, title=title)
            rows.append(
                MessageGeoRow(
                    message_id=message_id,
                    country=verdict.country,
                    status=verdict.status,
                    decided_by=verdict.decided_by,
                    engine_version=ENGINE_VERSION,
                    classified_at=now,
                )
            )
        await self.storage.put_message_geo_bulk(rows)
        await self.syslog(
            level=SystemLogLevel.NOTICE,
            event="geo.attributed",
            message=f"attributed {len(rows)} incident message(s)",
        )
        return len(rows)


__all__ = ["GeoAttributionService"]
