# SPDX-License-Identifier: AGPL-3.0-or-later
"""IndicatorExtractor — persist operational indicators + provenance per message.

Runs the DB-driven indicator ruleset over each raw message, upserts every match
into the deduped ``infrastructure_artifact`` store, and records an
``infrastructure_artifact_mention`` edge back to the message. This is the live
writer that turns the linker's recompute-from-bodies path into a persisted,
deduped, provenance-carrying artifact graph.

Idempotent at the storage layer: ``put_infrastructure_artifact`` dedups on
value_hash and ``record_artifact_mention`` dedups on ``(artifact_id, message_id)``,
so a re-delivered message adds no duplicate rows.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from eyenet.contracts.enums import InfrastructureKind
from eyenet.linker.indicators import extract, load_ruleset
from eyenet.search_indexer.events import publish_entity_changed

from ._base import DiscoveryExtractor

if TYPE_CHECKING:
    from eyenet.bus.publisher import BusEnvelopePublisher
    from eyenet.linker.indicators import CompiledRule
    from eyenet.storage.repository import BaseRepository

    from ._base import MessageContext

_log = structlog.get_logger()


class IndicatorExtractor(DiscoveryExtractor):
    """Extract + persist operational-infrastructure indicators from message text."""

    name = "indicator_extraction"

    def __init__(self, publisher: BusEnvelopePublisher | None = None) -> None:
        # ponytail: ruleset compiled once per process and cached. Operator rule
        # edits take effect on restart; a live reload signal is a later add if
        # editing-without-restart ever matters.
        self._ruleset: list[CompiledRule] | None = None
        # When set, publish entity.artifact.changed so the SearchIndexer reindexes
        # the artifact live (without it, artifacts land in search only via backfill).
        self._publisher = publisher

    async def process(self, ctx: MessageContext, storage: BaseRepository) -> int:
        if self._ruleset is None:
            self._ruleset = await load_ruleset(storage)
        indicators = extract(ctx.text, self._ruleset)
        if not indicators:
            return 0
        message_id = await storage.get_message_id_by_evidence_ref(ctx.evidence_ref)
        if message_id is None:
            _log.warning("indicator_extraction.unresolved_message", evidence_ref=ctx.evidence_ref)
            return 0
        for ind in indicators:
            try:
                kind = InfrastructureKind(ind.kind)
            except ValueError:
                # A rule's kind is operator data; a value outside the enum is a
                # misconfiguration, not a crash — log and skip this match.
                _log.warning("indicator_extraction.unknown_kind", kind=ind.kind)
                continue
            artifact = await storage.put_infrastructure_artifact(
                kind=kind,
                value=ind.value_norm,
                first_seen_at_ingest=ctx.collected_at,
                last_seen_at_ingest=ctx.collected_at,
            )
            inserted = await storage.record_artifact_mention(
                artifact_id=artifact.id,
                message_id=message_id,
                char_offset=ind.char_offset,
                ts=ctx.sent_at_source,
            )
            # Only emit on a genuinely new sighting, so a re-delivered message
            # does not re-trigger a reindex.
            if inserted and self._publisher is not None:
                await publish_entity_changed(
                    self._publisher,
                    entity_type="artifact",
                    entity_id=artifact.id,
                    source_id=artifact.resolved_to_source_id,
                )
        return len(indicators)


__all__ = ["IndicatorExtractor"]
