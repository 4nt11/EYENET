# SPDX-License-Identifier: AGPL-3.0-or-later
"""IndicatorExtractor: persist deduped artifacts + per-message provenance edges."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text

from eyenet.contracts.enums import GroupKind, InfrastructureKind, SourceKind
from eyenet.sensor.discovery import DISCOVERY_EXTRACTORS, IndicatorExtractor, MessageContext
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 6, 5, tzinfo=UTC)


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


async def _persist_message(storage: BaseRepository, body: str, n: int) -> MessageContext:
    from eyenet.models import MessageTable
    from eyenet.models._base import new_uuid7

    src = await storage.upsert_source(kind=SourceKind.TELEGRAM, display_name="tg", created_at=_NOW)
    gid, _ = await storage.upsert_group(
        source_id=src, platform_groupid="@g", kind=GroupKind.CHANNEL, title="g", seen_at=_NOW
    )
    actor, _ = await storage.upsert_actor(
        source_id=src,
        actor_key=f"actor:tg:{n}",
        platform_userid=str(n),
        handle=None,
        display_name=f"bot{n}",
        seen_at=_NOW,
    )
    evidence_ref = f"telegram:g:{n}"
    await storage.put_message(
        MessageTable(
            id=new_uuid7(),
            source_id=src,
            group_id=gid,
            actor_id=actor,
            platform_msgid=f"m{n}",
            evidence_ref=evidence_ref,
            body=body,
            length_chars=len(body),
            length_words=len(body.split()),
            sent_at_source=_NOW,
            ingested_at=_NOW,
        ),
        None,
    )
    return MessageContext(
        text=body,
        source_id=src,
        observed_by_collector_id=uuid4(),
        observed_in_group_id=gid,
        seed_root_id=None,
        depth_from_root=0,
        mentioning_actor_id=actor,
        evidence_ref=evidence_ref,
        sent_at_source=_NOW,
        collected_at=_NOW,
    )


def _count(storage: BaseRepository, table: str) -> int:
    with storage.sync_engine.connect() as c:  # type: ignore[attr-defined]
        return c.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()  # noqa: S608


async def test_registered_in_pipeline() -> None:
    assert any(isinstance(e, IndicatorExtractor) for e in DISCOVERY_EXTRACTORS)
    assert IndicatorExtractor.name == "indicator_extraction"


async def test_extracts_persists_and_records_mentions(storage: BaseRepository) -> None:
    body = "pay @wbpay_desk via 0xAbCdef0123456789abcdef0123456789ABCDEF01"
    ctx = await _persist_message(storage, body, 1)

    written = await IndicatorExtractor().process(ctx, storage)
    assert written == 2  # one handle + one eth wallet

    assert _count(storage, "infrastructure_artifact") == 2
    assert _count(storage, "infrastructure_artifact_mention") == 2

    # The eth wallet landed as its typed kind, deduped by value_hash.
    again = await storage.put_infrastructure_artifact(
        kind=InfrastructureKind.WALLET_ETH,
        value="0xabcdef0123456789abcdef0123456789abcdef01",
        first_seen_at_ingest=_NOW,
        last_seen_at_ingest=_NOW,
    )
    assert again.kind is InfrastructureKind.WALLET_ETH


async def test_dedup_artifact_across_messages_keeps_distinct_mentions(
    storage: BaseRepository,
) -> None:
    wallet = "0xAbCdef0123456789abcdef0123456789ABCDEF01"
    ctx1 = await _persist_message(storage, f"deposit {wallet}", 1)
    ctx2 = await _persist_message(storage, f"same wallet {wallet} again", 2)

    ext = IndicatorExtractor()
    await ext.process(ctx1, storage)
    await ext.process(ctx2, storage)

    assert _count(storage, "infrastructure_artifact") == 1  # one wallet, deduped
    assert _count(storage, "infrastructure_artifact_mention") == 2  # two sightings


async def test_reprocess_is_idempotent(storage: BaseRepository) -> None:
    ctx = await _persist_message(storage, "ping @wbpay_desk", 1)
    ext = IndicatorExtractor()
    await ext.process(ctx, storage)
    await ext.process(ctx, storage)  # re-delivery
    assert _count(storage, "infrastructure_artifact_mention") == 1
