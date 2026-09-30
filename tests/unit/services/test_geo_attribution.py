# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for the geo-attribution service + its storage sidecar methods.

Load-bearing behaviours: only INCIDENT-FLAGGED messages get attributed, the work
queue is idempotent (a message is attributed once), and the thread title feeds the
title-first geo engine.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from eyenet.bus import MemoryBus
from eyenet.contracts.enums import GroupKind, SourceKind
from eyenet.contracts.incident import IncidentRow
from eyenet.models import MessageTable
from eyenet.models._base import new_uuid7
from eyenet.services.geo_attribution import GeoAttributionService
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


async def _seed_message(storage: BaseRepository, *, body: str, title: str) -> object:
    now = datetime.now(tz=UTC)
    source_id = await storage.upsert_source(
        kind=SourceKind.FORUM, display_name="darkforums", created_at=now
    )
    group_id = await storage.upsert_group(
        source_id=source_id,
        platform_groupid=f"t-{new_uuid7().hex[:6]}",
        kind=GroupKind.FORUM_THREAD,
        title=title,
        seen_at=now,
    )
    actor_id = await storage.upsert_actor(
        source_id=source_id,
        actor_key=f"a-{new_uuid7().hex[:6]}",
        platform_userid="u1",
        handle=None,
        display_name=None,
        seen_at=now,
    )
    msg = MessageTable(
        id=new_uuid7(),
        source_id=source_id,
        group_id=group_id,
        actor_id=actor_id,
        platform_msgid=new_uuid7().hex[:8],
        evidence_ref=f"forum:{new_uuid7().hex}",
        body=body,
        length_chars=len(body),
        length_words=len(body.split()),
        sent_at_source=now,
        ingested_at=now,
    )
    await storage.put_message(msg)
    return msg.id


async def _flag_incident(storage: BaseRepository, message_id: object) -> None:
    await storage.put_incidents_bulk(
        [
            IncidentRow(
                message_id=message_id,
                labels=["data_breach"],
                scores={},
                model_version="test",
                classified_at=datetime.now(tz=UTC),
            )
        ]
    )


async def test_attributes_flagged_message_from_title(storage: BaseRepository) -> None:
    mid = await _seed_message(storage, body="dump inside", title="RedClinica CHILE 120gb")
    await _flag_incident(storage, mid)

    n = await GeoAttributionService(bus=MemoryBus(), storage=storage).attribute_batch()
    assert n == 1

    geo = await storage.message_geo_by_message_ids([mid])
    assert geo[mid].country == "CL"
    assert geo[mid].status == "resolved"
    assert geo[mid].engine_version  # stamped


async def test_body_pii_when_title_silent(storage: BaseRepository) -> None:
    mid = await _seed_message(storage, body="cliente 12.345.678-5", title="daily thread")
    await _flag_incident(storage, mid)
    await GeoAttributionService(bus=MemoryBus(), storage=storage).attribute_batch()
    geo = await storage.message_geo_by_message_ids([mid])
    assert geo[mid].country == "CL"
    assert geo[mid].decided_by == "national_id"


async def test_unflagged_message_is_not_attributed(storage: BaseRepository) -> None:
    mid = await _seed_message(storage, body="rut 12.345.678-5", title="Chile stuff")
    # no incident row and no operator label -> not in the work queue
    n = await GeoAttributionService(bus=MemoryBus(), storage=storage).attribute_batch()
    assert n == 0
    assert await storage.message_geo_by_message_ids([mid]) == {}


async def test_operator_rescued_message_is_attributed(storage: BaseRepository) -> None:
    # The young-classifier case: model missed it, operator labels it real via the reader.
    mid = await _seed_message(storage, body="dump", title="RedClinica CHILE")
    await storage.set_incident_label(
        mid, ["data_breach"], decided_by="anti", reason=None, decided_at=datetime.now(tz=UTC)
    )
    n = await GeoAttributionService(bus=MemoryBus(), storage=storage).attribute_batch()
    assert n == 1
    geo = await storage.message_geo_by_message_ids([mid])
    assert geo[mid].country == "CL"


async def test_operator_false_positive_is_not_attributed(storage: BaseRepository) -> None:
    # Operator marks a message NOT an incident (empty label) -> stays out of the queue.
    mid = await _seed_message(storage, body="rut 12.345.678-5", title="Chile")
    await storage.set_incident_label(
        mid, [], decided_by="anti", reason="false positive", decided_at=datetime.now(tz=UTC)
    )
    n = await GeoAttributionService(bus=MemoryBus(), storage=storage).attribute_batch()
    assert n == 0


async def test_work_queue_is_idempotent(storage: BaseRepository) -> None:
    mid = await _seed_message(storage, body="x", title="Russia Alfa Bank")
    await _flag_incident(storage, mid)
    svc = GeoAttributionService(bus=MemoryBus(), storage=storage)
    assert await svc.attribute_batch() == 1
    assert await svc.attribute_batch() == 0  # already attributed, not re-processed

    needing = await storage.messages_needing_geo(limit=10)
    assert needing == []


async def _seed_thread(
    storage: BaseRepository, *, pgid: str, title: str, op_body: str, op_sent: datetime
) -> object:
    now = datetime.now(tz=UTC)
    source_id = await storage.upsert_source(
        kind=SourceKind.FORUM, display_name="darkforums", created_at=now
    )
    g = await storage.upsert_group(
        source_id=source_id,
        platform_groupid=pgid,
        kind=GroupKind.FORUM_THREAD,
        title=title,
        seen_at=now,
    )
    await storage.record_forum_thread_link(
        source_id=source_id,
        category_platform_groupid="cat1",
        thread_platform_groupid=pgid,
        seen_at=now,
    )
    actor = await storage.upsert_actor(
        source_id=source_id,
        actor_key="a" + pgid,
        platform_userid="u",
        handle=None,
        display_name=None,
        seen_at=now,
    )
    op = MessageTable(
        id=new_uuid7(),
        source_id=source_id,
        group_id=g,
        actor_id=actor,
        platform_msgid=pgid + "-1",
        evidence_ref="f:" + pgid,
        body=op_body,
        length_chars=len(op_body),
        length_words=len(op_body.split()),
        sent_at_source=op_sent,
        ingested_at=now,
    )
    await storage.put_message(op)
    return source_id


async def test_thread_summary_from_op_title(storage: BaseRepository) -> None:
    now = datetime.now(tz=UTC)
    sid = await _seed_thread(
        storage, pgid="t1", title="RedClinica CHILE", op_body="dump", op_sent=now
    )
    n = await GeoAttributionService(bus=MemoryBus(), storage=storage).summarize_threads_batch()
    assert n == 1
    rows = await storage.list_threads_for_category(
        source_id=sid, category_platform_groupid="cat1", limit=10
    )
    _g, summary = rows[0]
    assert summary is not None
    assert summary.victim_country == "CL"


async def test_thread_summary_country_filter_and_idempotent(storage: BaseRepository) -> None:
    now = datetime.now(tz=UTC)
    sid = await _seed_thread(storage, pgid="t1", title="RedClinica CHILE", op_body="x", op_sent=now)
    await _seed_thread(storage, pgid="t2", title="Russia Alfa Bank", op_body="x", op_sent=now)
    svc = GeoAttributionService(bus=MemoryBus(), storage=storage)
    assert await svc.summarize_threads_batch() == 2
    assert await svc.summarize_threads_batch() == 0  # idempotent

    cl = await storage.list_threads_for_category(
        source_id=sid, category_platform_groupid="cat1", limit=10, countries=["CL"]
    )
    assert len(cl) == 1
    assert cl[0][1].victim_country == "CL"


async def test_messages_needing_geo_returns_title(storage: BaseRepository) -> None:
    mid = await _seed_message(storage, body="body text", title="Peru RENIEC")
    await _flag_incident(storage, mid)
    pending = await storage.messages_needing_geo(limit=10)
    assert len(pending) == 1
    got_id, _body, title = pending[0]
    assert got_id == mid
    assert title == "Peru RENIEC"
