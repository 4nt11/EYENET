# SPDX-License-Identifier: AGPL-3.0-or-later
"""induced_edges — derived edges among search-result nodes (GLOBAL_SEARCH.md §10.3).

Exercises the scoping invariant (an edge appears only when BOTH endpoints are in
the node set) via linkage rows; the other derived edge types use the same clause.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from eyenet.contracts.enums import GroupKind, LinkageState
from eyenet.models import MessageTable
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
async def test_same_author_thread_edges(storage: BaseRepository) -> None:
    """Threads whose OP (earliest post) is the same actor get a derived same_author
    edge; a thread by a different author does not join them."""
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
    await _op(threads["t2"], author, "p2", datetime(2026, 1, 2, tzinfo=UTC))
    await _op(threads["t3"], other, "p3", datetime(2026, 1, 3, tzinfo=UTC))

    edges = await storage.induced_edges(
        actor_ids=[], persona_ids=[], artifact_ids=[], thread_ids=list(threads.values())
    )
    sa = [e for e in edges if e["kind"] == "same_author"]
    assert len(sa) == 1  # t1<->t2 only; t3 (different author) is not joined
    assert {sa[0]["src_id"], sa[0]["dst_id"]} == {threads["t1"], threads["t2"]}
    assert sa[0]["meta"]["actor_id"] == str(author)
    await storage.close()
