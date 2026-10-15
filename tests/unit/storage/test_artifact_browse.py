# SPDX-License-Identifier: AGPL-3.0-or-later
"""Artifact browse surface: read-time mention aggregates + the mentioned-by drill-down.

Exercises list_infrastructure_artifacts (how many / by who / where / when) and
list_artifact_mentions over the deduped artifact + mention-edge graph.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from eyenet.contracts.enums import GroupKind, ResolutionState, SourceKind
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 6, 5, tzinfo=UTC)


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


async def _msg(storage: BaseRepository, *, src, gid, actor, n: int, ts: datetime) -> None:
    from eyenet.models import MessageTable
    from eyenet.models._base import new_uuid7

    await storage.put_message(
        MessageTable(
            id=new_uuid7(),
            source_id=src,
            group_id=gid,
            actor_id=actor,
            platform_msgid=f"m{n}",
            evidence_ref=f"telegram:g:{n}",
            body=f"body {n}",
            length_chars=6,
            length_words=2,
            sent_at_source=ts,
            ingested_at=ts,
        ),
        None,
    )


async def _mid(storage: BaseRepository, n: int):
    return await storage.get_message_id_by_evidence_ref(f"telegram:g:{n}")


async def _seed(storage: BaseRepository):
    src = await storage.upsert_source(kind=SourceKind.TELEGRAM, display_name="tg", created_at=_NOW)
    g1, _ = await storage.upsert_group(
        source_id=src,
        platform_groupid="@g1",
        kind=GroupKind.CHANNEL,
        title="Group One",
        seen_at=_NOW,
    )
    g2, _ = await storage.upsert_group(
        source_id=src,
        platform_groupid="@g2",
        kind=GroupKind.CHANNEL,
        title="Group Two",
        seen_at=_NOW,
    )
    a1, _ = await storage.upsert_actor(
        source_id=src,
        actor_key="a1",
        platform_userid="1",
        handle="alpha",
        display_name="Alpha",
        seen_at=_NOW,
    )
    a2, _ = await storage.upsert_actor(
        source_id=src,
        actor_key="a2",
        platform_userid="2",
        handle="bravo",
        display_name="Bravo",
        seen_at=_NOW,
    )
    await _msg(storage, src=src, gid=g1, actor=a1, n=1, ts=_NOW)
    await _msg(storage, src=src, gid=g1, actor=a2, n=2, ts=_NOW + timedelta(hours=1))
    await _msg(storage, src=src, gid=g2, actor=a1, n=3, ts=_NOW + timedelta(hours=2))
    return src, (a1, a2)


async def _put(storage: BaseRepository, kind: str, value: str):
    return await storage.put_infrastructure_artifact(
        kind=kind, value=value, first_seen_at_ingest=_NOW, last_seen_at_ingest=_NOW
    )


async def test_browse_aggregates_who_where_when(storage: BaseRepository) -> None:
    await _seed(storage)
    x = await _put(storage, "domain", "evil.su")  # 3 mentions, 2 actors, 2 groups
    y = await _put(storage, "ipv4", "8.8.8.8")  # 1 mention
    await _put(storage, "domain", "lonely.io")  # 0 mentions (outer join -> zeros)

    for n, ts in ((1, _NOW), (2, _NOW + timedelta(hours=1)), (3, _NOW + timedelta(hours=2))):
        await storage.record_artifact_mention(
            artifact_id=x.id, message_id=await _mid(storage, n), char_offset=None, ts=ts
        )
    await storage.record_artifact_mention(
        artifact_id=y.id, message_id=await _mid(storage, 1), char_offset=5, ts=_NOW
    )

    rows = await storage.list_infrastructure_artifacts(limit=50, offset=0)
    by_value = {art.value: agg for art, *agg in rows}
    assert by_value["evil.su"] == [3, 2, 2, _NOW, _NOW + timedelta(hours=2)]
    assert by_value["8.8.8.8"][:3] == [1, 1, 1]
    assert by_value["lonely.io"][:3] == [0, 0, 0]  # unmentioned artifact still listed


async def test_browse_filters(storage: BaseRepository) -> None:
    await _seed(storage)
    await _put(storage, "domain", "evil.su")
    await _put(storage, "domain", "lonely.io")
    await _put(storage, "ipv4", "8.8.8.8")

    only_domains = await storage.list_infrastructure_artifacts(kind="domain", limit=50, offset=0)
    assert {a.value for a, *_ in only_domains} == {"evil.su", "lonely.io"}
    assert await storage.count_infrastructure_artifacts(kind="domain") == 2

    hits = await storage.list_infrastructure_artifacts(q="EVIL", limit=50, offset=0)  # ci substring
    assert {a.value for a, *_ in hits} == {"evil.su"}


async def test_mentions_drilldown(storage: BaseRepository) -> None:
    await _seed(storage)
    x = await _put(storage, "domain", "evil.su")
    for n, ts in ((1, _NOW), (2, _NOW + timedelta(hours=1))):
        await storage.record_artifact_mention(
            artifact_id=x.id, message_id=await _mid(storage, n), char_offset=None, ts=ts
        )

    mentions = await storage.list_artifact_mentions(x.id, limit=50, offset=0)
    assert len(mentions) == 2
    # newest first: message n=2 (Bravo, Group One) then n=1 (Alpha, Group One)
    handles = [row[2] for row in mentions]
    titles = [row[5] for row in mentions]
    assert handles == ["bravo", "alpha"]
    assert titles == ["Group One", "Group One"]
    assert await storage.count_artifact_mentions(x.id) == 2


async def test_resolution_state_filter(storage: BaseRepository) -> None:
    await _seed(storage)
    await _put(storage, "ipv4", "8.8.8.8")  # NOT_APPLICABLE (IPs don't bridge)
    rows = await storage.list_infrastructure_artifacts(
        resolution_state=ResolutionState.NOT_APPLICABLE, limit=50, offset=0
    )
    assert {a.value for a, *_ in rows} == {"8.8.8.8"}
