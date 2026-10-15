# SPDX-License-Identifier: AGPL-3.0-or-later
"""induced_edges — derived edges among search-result nodes (GLOBAL_SEARCH.md §10.3).

Exercises the scoping invariant (an edge appears only when BOTH endpoints are in
the node set) via linkage rows; the other derived edge types use the same clause.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from eyenet.contracts.enums import GroupKind, LinkageState, ResolutionState
from eyenet.models import (
    InfrastructureArtifactMentionTable,
    InfrastructureArtifactTable,
    MessageTable,
)
from eyenet.models.linkage import LinkageTable
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository
from tests._seed import seed_telegram_fixture

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 10, 5, tzinfo=UTC)


@pytest.fixture
def storage(monkeypatch: pytest.MonkeyPatch) -> BaseRepository:
    monkeypatch.setenv("EYENET_STORAGE_TYPE", "sqlite")
    return get_repository(in_memory=True)


@pytest.mark.asyncio
async def test_induced_edges_scopes_to_node_set(storage: BaseRepository) -> None:
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    # the linkage table enforces a canonical ordered pair (actor_a_id < actor_b_id).
    ab_lo, ab_hi = sorted((a, b))
    ac_lo, ac_hi = sorted((a, c))
    async with storage.session() as s:
        s.add(
            LinkageTable(
                actor_a_id=ab_lo,
                actor_b_id=ab_hi,
                state=LinkageState.CONFIRMED,
                method="shared_infra",
                score=0.9,
                proposed_at=_NOW,
            )
        )
        s.add(
            LinkageTable(
                actor_a_id=ac_lo,
                actor_b_id=ac_hi,
                state=LinkageState.PROPOSED,
                method="shared_infra",
                score=0.5,
                proposed_at=_NOW,
            )
        )
        await s.commit()

    # a and b are nodes -> the a-b edge is induced; c is NOT a node -> a-c excluded.
    edges = await storage.induced_edges(actor_ids=[a, b], persona_ids=[], artifact_ids=[])
    linked = [e for e in edges if e["kind"] == "linked"]
    assert len(linked) == 1
    e = linked[0]
    assert {e["src_id"], e["dst_id"]} == {a, b}
    assert e["weight"] == 0.9
    assert e["meta"]["state"] == "confirmed"

    # no actor nodes -> no edges
    assert await storage.induced_edges(actor_ids=[], persona_ids=[], artifact_ids=[]) == []
    await storage.close()


@pytest.mark.asyncio
async def test_thread_op_authors_resolves_earliest_poster(storage: BaseRepository) -> None:
    """thread_op_authors maps each thread to its OP (earliest-post) author + handle,
    so the graph endpoint can hub threads on the real actor node."""
    src, _g, _a = await seed_telegram_fixture(
        storage, [{"actor_key": "k", "platform_msgid": "1", "body": "x"}], _NOW
    )
    author, _ = await storage.upsert_actor(
        source_id=src,
        actor_key="k_auth",
        platform_userid="auth",
        handle="auth",
        display_name="auth",
        seen_at=_NOW,
    )
    other, _ = await storage.upsert_actor(
        source_id=src,
        actor_key="k_oth",
        platform_userid="oth",
        handle="oth",
        display_name="oth",
        seen_at=_NOW,
    )
    threads = {}
    for name in ("t1", "t2", "t3"):
        tid, _ = await storage.upsert_group(
            source_id=src,
            platform_groupid=name,
            kind=GroupKind.FORUM_THREAD,
            title=name.upper(),
            seen_at=_NOW,
        )
        threads[name] = tid

    async def _op(tid, aid, pid, when):
        await storage.put_message(
            MessageTable(
                source_id=src,
                group_id=tid,
                actor_id=aid,
                platform_msgid=pid,
                evidence_ref=f"f:{pid}",
                body="op",
                length_chars=2,
                length_words=1,
                sent_at_source=when,
                ingested_at=_NOW,
            ),
            [],
        )

    await _op(threads["t1"], author, "p1", datetime(2026, 1, 1, tzinfo=UTC))
    await _op(threads["t1"], other, "p1b", datetime(2026, 1, 5, tzinfo=UTC))  # later reply
    await _op(threads["t2"], author, "p2", datetime(2026, 1, 2, tzinfo=UTC))
    await _op(threads["t3"], other, "p3", datetime(2026, 1, 3, tzinfo=UTC))

    authors = await storage.thread_op_authors(list(threads.values()))
    assert authors[threads["t1"]][0] == author  # earliest poster, not the later replier
    assert authors[threads["t2"]][0] == author
    assert authors[threads["t3"]][0] == other
    assert authors[threads["t1"]][1] == "auth"  # handle
    await storage.close()


@pytest.mark.asyncio
async def test_message_authors_maps_sender(storage: BaseRepository) -> None:
    """message_authors maps each message to its attributed sender (actor_id, handle)."""
    src, group_id, _a = await seed_telegram_fixture(
        storage, [{"actor_key": "k", "platform_msgid": "0", "body": "seed"}], _NOW
    )
    sender, _ = await storage.upsert_actor(
        source_id=src, actor_key="k_s", platform_userid="sender",
        handle="sender", display_name="sender", seen_at=_NOW,
    )
    msg = MessageTable(
        source_id=src, group_id=group_id, actor_id=sender, platform_msgid="m1",
        evidence_ref="msg:1", body="leak drop", length_chars=9, length_words=2,
        sent_at_source=_NOW, ingested_at=_NOW,
    )
    await storage.put_message(msg, [])

    got = await storage.message_authors([msg.id])
    assert got[msg.id][0] == sender
    assert got[msg.id][1] == "sender"
    assert await storage.message_authors([]) == {}
    await storage.close()


@pytest.mark.asyncio
async def test_artifact_mention_edges_scopes_to_node_set(storage: BaseRepository) -> None:
    """artifact->message provenance edges appear only when BOTH are result nodes."""
    src, group_id, _a = await seed_telegram_fixture(
        storage, [{"actor_key": "k", "platform_msgid": "0", "body": "seed"}], _NOW
    )
    hit = MessageTable(
        source_id=src, group_id=group_id, actor_id=_a["k"], platform_msgid="hit",
        evidence_ref="msg:hit", body="onion drop", length_chars=10, length_words=2,
        sent_at_source=_NOW, ingested_at=_NOW,
    )
    miss = MessageTable(
        source_id=src, group_id=group_id, actor_id=_a["k"], platform_msgid="miss",
        evidence_ref="msg:miss", body="onion drop", length_chars=10, length_words=2,
        sent_at_source=_NOW, ingested_at=_NOW,
    )
    await storage.put_message(hit, [])
    await storage.put_message(miss, [])

    art = InfrastructureArtifactTable(
        kind="onion", value="x.onion", value_hash="h",
        first_seen_at_ingest=_NOW, last_seen_at_ingest=_NOW,
        resolution_state=ResolutionState.UNRESOLVED,
    )
    async with storage.session() as s:
        s.add(art)
        await s.flush()
        s.add(InfrastructureArtifactMentionTable(artifact_id=art.id, message_id=hit.id, ts=_NOW))
        s.add(InfrastructureArtifactMentionTable(artifact_id=art.id, message_id=miss.id, ts=_NOW))
        await s.commit()

    # Only `hit` is a result node -> only that provenance edge is induced.
    edges = await storage.artifact_mention_edges(artifact_ids=[art.id], message_ids=[hit.id])
    assert edges == [(art.id, hit.id)]
    # No artifact nodes, or no message nodes -> no edges.
    assert await storage.artifact_mention_edges(artifact_ids=[], message_ids=[hit.id]) == []
    assert await storage.artifact_mention_edges(artifact_ids=[art.id], message_ids=[]) == []
    await storage.close()
