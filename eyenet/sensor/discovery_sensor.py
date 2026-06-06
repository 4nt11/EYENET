# SPDX-License-Identifier: AGPL-3.0-or-later
"""`DiscoverySensor` — runs the discovery extractors over every raw message (M9.E2).

Subscribes to ``raw.message.>`` in its own queue group (independent of the
stylometric ``sensor`` group, so it sees every message), resolves the
:class:`~eyenet.contracts.raw_message.RawMessageEnvelope`'s opaque strings into
a :class:`~eyenet.sensor.discovery.MessageContext` of UUIDs + lineage, then runs
every registered :class:`~eyenet.sensor.discovery.DiscoveryExtractor`.

Resolution (the integration crux of E1+E2):
- ``instance_id`` → collector via ``resolve_collector_by_instance_id`` (the 8-char
  id is a hash, reverse-matched against the fleet); the collector carries
  ``source_id``.
- ``platform_groupid`` → group via ``upsert_group`` (the observed-in group nearly
  always already exists, since the collector is a member); its lineage gives the
  seed root + depth the extractors propagate.
- ``actor_key`` → actor via ``resolve_actor_id`` (registered at ingest time).

A message that can't be attributed (unknown collector / actor / missing body) is
skipped — discovery is best-effort and must never block the bus fan-out.
"""

from __future__ import annotations

import asyncio

from eyenet.contracts.enums import GroupKind, SourceKind
from eyenet.contracts.raw_message import RawMessageEnvelope
from eyenet.sensor.discovery import DISCOVERY_EXTRACTORS, MessageContext
from eyenet.service import ServiceBase
from eyenet.telemetry.logging import get_logger
from eyenet.telemetry.propagation import attach_from_headers

_log = get_logger()
_INSTANCE = "discovery_default"

# Best-effort group kind when upsert_group must CREATE the observed-in group
# (the envelope carries no GroupKind). An existing group keeps its own kind on
# conflict, so this only matters for a never-before-seen group.
_DEFAULT_GROUP_KIND: dict[SourceKind, GroupKind] = {
    SourceKind.TELEGRAM: GroupKind.CHANNEL,
    SourceKind.MATRIX: GroupKind.MATRIX_ROOM,
    SourceKind.IRC: GroupKind.IRC_CHANNEL,
}


class DiscoverySensor(ServiceBase):
    """Per-message discovery extractor dispatcher (M9.E2)."""

    @property
    def name(self) -> str:
        return "discovery_sensor"

    @property
    def instance_id(self) -> str:
        return _INSTANCE

    async def on_subscribe(self) -> None:
        async def _handler(_subject: str, payload: bytes, headers: dict[str, str]) -> None:
            try:
                env = RawMessageEnvelope.model_validate_json(payload)
            except ValueError as exc:
                _log.error("discovery_sensor.envelope_parse_error", error=str(exc))
                return
            # Fire-and-forget so discovery never blocks the bus fan-out.
            asyncio.create_task(self._dispatch(env, headers))  # noqa: RUF006

        await self._bus.subscribe("raw.message.>", _handler, queue_group="discovery")

    async def _dispatch(self, env: RawMessageEnvelope, headers: dict[str, str]) -> None:
        with attach_from_headers(headers):
            ctx = await self._resolve(env)
            if ctx is None:
                return
            for extractor in DISCOVERY_EXTRACTORS:
                await extractor.process(ctx, self._storage)

    async def _resolve(self, env: RawMessageEnvelope) -> MessageContext | None:
        collector = await self._storage.resolve_collector_by_instance_id(env.instance_id)
        if collector is None:
            _log.warning("discovery_sensor.unknown_collector", instance_id=env.instance_id)
            return None

        actor_id = await self._storage.resolve_actor_id(env.actor_key)
        if actor_id is None:
            _log.warning("discovery_sensor.unresolved_actor", actor_key=env.actor_key)
            return None

        body = await self._storage.get_message_body(env.evidence_ref)
        if body is None:
            _log.warning("discovery_sensor.missing_body", evidence_ref=env.evidence_ref)
            return None

        group_id = await self._storage.upsert_group(
            source_id=collector.source_id,
            platform_groupid=env.platform_groupid,
            kind=_DEFAULT_GROUP_KIND.get(env.source, GroupKind.CHAT),
            title=None,
            seen_at=env.collected_at,
        )
        seed_root_id, depth = await self._storage.group_lineage(group_id)

        return MessageContext(
            text=body.decode("utf-8", errors="replace"),
            source_id=collector.source_id,
            observed_by_collector_id=collector.id,
            observed_in_group_id=group_id,
            seed_root_id=seed_root_id,
            depth_from_root=depth,
            mentioning_actor_id=actor_id,
            evidence_ref=env.evidence_ref,
            sent_at_source=env.sent_at_source,
            collected_at=env.collected_at,
        )


__all__ = ["DiscoverySensor"]
