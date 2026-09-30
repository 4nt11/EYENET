"""Integration test for the discovery BACKFILL path (M9.E2 gap-fill).

The live DiscoverySensor only sees new messages off the bus; the backfill mines
the STORED corpus. This exercises the new storage primitive
(``messages_for_discovery_backfill`` — the keyset walk joined to each message's
first-sighting collector) and the same extractor loop the ``discovery-backfill``
CLI command runs, asserting a channel reference in a stored body becomes a
DISCOVERED candidate that nothing auto-joins.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from eyenet.contracts.enums import CandidateState, GroupKind, SourceKind
from eyenet.models.message import MessageTable
from eyenet.sensor.discovery import DISCOVERY_EXTRACTORS, MessageContext
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository
from eyenet.storage.sqlmodel_repo.messages import DiscoveryBackfillMessage

_NOW = datetime(2026, 6, 6, tzinfo=UTC)
pytestmark = pytest.mark.integration


async def _seed(storage: BaseRepository) -> tuple[UUID, UUID, UUID]:
    """Seed source/identity/collector/actor/group/message. Returns
    (source_id, collector_id, message_id). No message_observation row: the
    backfill deliberately does NOT depend on one (historical rows lack it)."""
    src = await storage.upsert_source(
        kind=SourceKind.TELEGRAM, display_name="telegram:s", created_at=_NOW
    )
    ident = await storage.create_identity(name="tg_alpha", source_id=src, session_path="/a")
    collector = await storage.create_collector(
        instance_name="collector-alpha",
        kind=SourceKind.TELEGRAM,
        source_id=src,
        identity_id=ident.id,
        config={},
        created_at=_NOW,
        created_by_user_id=UUID(int=1),
    )
    actor_id = await storage.upsert_actor(
        source_id=src,
        actor_key="actor:1",
        platform_userid="1",
        handle="poster",
        display_name=None,
        seen_at=_NOW,
    )
    group = await storage.upsert_group(
        source_id=src,
        platform_groupid="rootgroup",
        kind=GroupKind.CHANNEL,
        title="root",
        seen_at=_NOW,
    )
    msg_id = uuid4()
    body = "join @target_channel now"
    await storage.put_message(
        MessageTable(
            id=msg_id,
            source_id=src,
            group_id=group,
            actor_id=actor_id,
            platform_msgid="100",
            evidence_ref="tg:rootgroup:100",
            body=body,
            length_chars=len(body),
            length_words=len(body.split()),
            sent_at_source=_NOW,
            ingested_at=_NOW,
        )
    )
    return src, collector.id, msg_id


async def test_backfill_primitive_returns_message() -> None:
    storage = get_repository(in_memory=True)
    _src, _collector_id, msg_id = await _seed(storage)

    page = await storage.messages_for_discovery_backfill(limit=100)

    assert len(page) == 1
    row = page[0]
    assert isinstance(row, DiscoveryBackfillMessage)
    assert row.id == msg_id
    assert "@target_channel" in row.body


async def test_backfill_loop_records_discovered_candidate_no_autojoin() -> None:
    storage = get_repository(in_memory=True)
    _src, collector_id, _msg_id = await _seed(storage)

    # Mirror the discovery-backfill CLI loop: resolve the observing collector
    # per source (message_observation is not populated for historical rows).
    collectors = await storage.list_collectors()
    source_collector = {c.source_id: c.id for c in collectors}

    page = await storage.messages_for_discovery_backfill(limit=100)
    for m in page:
        assert isinstance(m, DiscoveryBackfillMessage)
        seed_root_id, depth = await storage.group_lineage(m.group_id)
        ctx = MessageContext(
            text=m.body,
            source_id=m.source_id,
            observed_by_collector_id=source_collector[m.source_id],
            observed_in_group_id=m.group_id,
            seed_root_id=seed_root_id,
            depth_from_root=depth,
            mentioning_actor_id=m.actor_id,
            evidence_ref=m.evidence_ref,
            sent_at_source=m.sent_at_source,
            collected_at=m.ingested_at,
        )
        for extractor in DISCOVERY_EXTRACTORS:
            await extractor.process(ctx, storage)

    assert collector_id in source_collector.values()

    cands = await storage.list_candidates(limit=10)
    assert len(cands) == 1
    assert cands[0].platform_groupid == "@target_channel"
    assert cands[0].state is CandidateState.DISCOVERED  # nothing auto-joins
    assert cands[0].member_dialog is False  # via mention descent, not a dialog scan


async def test_backfill_keyset_paging_terminates() -> None:
    storage = get_repository(in_memory=True)
    await _seed(storage)

    first = await storage.messages_for_discovery_backfill(limit=100)
    assert len(first) == 1
    # Passing the last id back yields an empty page → the walk ends.
    assert await storage.messages_for_discovery_backfill(limit=100, after_id=first[0].id) == []
