# SPDX-License-Identifier: AGPL-3.0-or-later
"""graph_expand — neighbour expansion for /v1/graph/expand.

Nodes hydrate from search_document, so an entity must be indexed to appear.
Exercises the actor/artifact/message enrichments, the single-neighbour path,
the degree counts, and the unknown-enrichment guard.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from eyenet.contracts.enums import AttachmentKind, GroupKind, SensitivityTier, SourceKind
from eyenet.models import AttachmentTable, IncidentTable, MessageTable, ThreadSummaryTable
from eyenet.models._base import new_uuid7
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 6, 5, tzinfo=UTC)


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


async def _seed(storage: BaseRepository):
    src = await storage.upsert_source(kind=SourceKind.FORUM, display_name="f", created_at=_NOW)
    gid, _ = await storage.upsert_group(
        source_id=src, platform_groupid="t1", kind=GroupKind.FORUM_THREAD, title="T", seen_at=_NOW
    )
    actor, _ = await storage.upsert_actor(
        source_id=src,
        actor_key="a",
        platform_userid="1",
        handle="zfo",
        display_name="zfo",
        seen_at=_NOW,
    )
    mid = new_uuid7()
    await storage.put_message(
        MessageTable(
            id=mid,
            source_id=src,
            group_id=gid,
            actor_id=actor,
            platform_msgid="m1",
            evidence_ref="mybb:1",
            body="x.onion",
            length_chars=7,
            length_words=1,
            sent_at_source=_NOW,
            ingested_at=_NOW,
        ),
        None,
    )
    ids = await storage.put_infrastructure_artifacts_bulk([("onion", "x.onion", _NOW, _NOW)])
    art = next(iter(ids.values()))
    await storage.record_artifact_mentions_bulk([(art, mid, None, _NOW)])
    # index for hydration
    await storage.put_search_document(entity_type="actor", entity_id=actor, title="zfo")
    await storage.put_search_document(entity_type="message", entity_id=mid, title="post")
    await storage.put_search_document(
        entity_type="artifact", entity_id=art, title="x.onion", kind="onion"
    )
    await storage.put_search_document(entity_type="thread", entity_id=gid, title="T")
    return src, gid, actor, mid, art


async def test_actor_messages_edge_and_total(storage: BaseRepository) -> None:
    _src, _gid, actor, mid, _art = await _seed(storage)
    nodes, edges, total, more = await storage.graph_expand(
        src_type="actor", src_id=actor, enrichment="messages", limit=10, offset=0, want_total=True
    )
    assert [n.entity_id for n in nodes] == [mid]
    assert nodes[0].entity_type == "message"
    assert edges == [{"src_id": actor, "dst_id": mid, "kind": "authored"}]
    assert total == 1
    assert more is False
    await storage.close()


async def test_artifact_bridges_to_message_and_actor(storage: BaseRepository) -> None:
    _src, _gid, actor, mid, art = await _seed(storage)
    msgs, _e, _t, _m = await storage.graph_expand(
        src_type="artifact", src_id=art, enrichment="messages", limit=10, offset=0, want_total=False
    )
    assert [n.entity_id for n in msgs] == [mid]
    actors, edges, _t2, _m2 = await storage.graph_expand(
        src_type="artifact", src_id=art, enrichment="actors", limit=10, offset=0, want_total=False
    )
    assert [n.entity_id for n in actors] == [actor]
    assert edges[0]["kind"] == "mentioned_by"
    await storage.close()


async def test_actor_source_is_single(storage: BaseRepository) -> None:
    src, _gid, actor, _mid, _art = await _seed(storage)
    nodes, edges, total, more = await storage.graph_expand(
        src_type="actor", src_id=actor, enrichment="source", limit=10, offset=0, want_total=True
    )
    assert [n.entity_id for n in nodes] == [src]
    assert nodes[0].entity_type == "source"
    assert nodes[0].title == "f"  # the seed source display_name
    assert edges[0]["kind"] == "from_source"
    assert total == 1
    assert more is False
    await storage.close()


async def test_url_artifact_to_domain(storage: BaseRepository) -> None:
    import hashlib

    def _h(v: str) -> str:
        return hashlib.sha256(v.encode("utf-8")).hexdigest()

    ids = await storage.put_infrastructure_artifacts_bulk(
        [("domain", "t.me", _NOW, _NOW), ("url", "https://t.me/zfoleaks", _NOW, _NOW)]
    )
    dom = ids[_h("t.me")]
    url = ids[_h("https://t.me/zfoleaks")]
    nodes, edges, total, more = await storage.graph_expand(
        src_type="artifact", src_id=url, enrichment="domain", limit=10, offset=0, want_total=True
    )
    assert [n.entity_id for n in nodes] == [dom]
    assert nodes[0].fields["value"] == "t.me"
    assert edges[0]["kind"] == "on_domain"
    assert total == 1
    assert more is False
    await storage.close()


async def test_actor_started_threads(storage: BaseRepository) -> None:
    _src, gid, actor, mid, _art = await _seed(storage)
    # Make the actor the OP of the (forum_thread) group via the canonical thread_summary.
    async with storage.session() as s:
        s.add(
            ThreadSummaryTable(
                group_id=gid,
                op_message_id=mid,
                op_sent_at=_NOW,
                victim_status="unknown",
                engine_version="test",
                computed_at=_NOW,
            )
        )
        await s.commit()
    nodes, edges, total, more = await storage.graph_expand(
        src_type="actor", src_id=actor, enrichment="started", limit=10, offset=0, want_total=True
    )
    assert [n.entity_id for n in nodes] == [gid]
    assert nodes[0].entity_type == "thread"
    assert edges[0]["kind"] == "started"
    assert total == 1
    assert more is False
    await storage.close()


async def test_actor_replied_in_threads(storage: BaseRepository) -> None:
    src = await storage.upsert_source(kind=SourceKind.FORUM, display_name="f", created_at=_NOW)
    gid, _ = await storage.upsert_group(
        source_id=src, platform_groupid="t9", kind=GroupKind.FORUM_THREAD, title="T9", seen_at=_NOW
    )
    opener, _ = await storage.upsert_actor(
        source_id=src,
        actor_key="op",
        platform_userid="10",
        handle="op",
        display_name="op",
        seen_at=_NOW,
    )
    replier, _ = await storage.upsert_actor(
        source_id=src,
        actor_key="rep",
        platform_userid="11",
        handle="rep",
        display_name="rep",
        seen_at=_NOW,
    )
    op_mid, rep_mid = new_uuid7(), new_uuid7()
    for mid, who, ref in ((op_mid, opener, "mybb:op"), (rep_mid, replier, "mybb:rep")):
        await storage.put_message(
            MessageTable(
                id=mid,
                source_id=src,
                group_id=gid,
                actor_id=who,
                platform_msgid=ref,
                evidence_ref=ref,
                body="x",
                length_chars=1,
                length_words=1,
                sent_at_source=_NOW,
                ingested_at=_NOW,
            ),
            None,
        )
    async with storage.session() as s:
        s.add(
            ThreadSummaryTable(
                group_id=gid,
                op_message_id=op_mid,
                op_sent_at=_NOW,
                victim_status="unknown",
                engine_version="test",
                computed_at=_NOW,
            )
        )
        await s.commit()
    await storage.put_search_document(entity_type="thread", entity_id=gid, title="T9")
    # replier posted but didn't start -> replied_in returns the thread
    nodes, edges, _t, _m = await storage.graph_expand(
        src_type="actor",
        src_id=replier,
        enrichment="replied_in",
        limit=10,
        offset=0,
        want_total=False,
    )
    assert [n.entity_id for n in nodes] == [gid]
    assert edges[0]["kind"] == "replied_in"
    # the OP themselves did start it -> replied_in is empty for them
    op_nodes, _e, _t2, _m2 = await storage.graph_expand(
        src_type="actor",
        src_id=opener,
        enrichment="replied_in",
        limit=10,
        offset=0,
        want_total=False,
    )
    assert op_nodes == []
    await storage.close()


async def test_message_incidents(storage: BaseRepository) -> None:
    _src, _gid, _actor, mid, _art = await _seed(storage)
    async with storage.session() as s:
        s.add(
            IncidentTable(
                message_id=mid,
                labels=["data_breach", "credential_leak"],
                scores={"data_breach": 0.91},
                model_version="test-v1",
                classified_at=_NOW,
            )
        )
        await s.commit()
    nodes, edges, total, more = await storage.graph_expand(
        src_type="message", src_id=mid, enrichment="incidents", limit=10, offset=0, want_total=True
    )
    assert len(nodes) == 1
    assert nodes[0].entity_type == "incident"
    assert nodes[0].fields["labels"] == ["data_breach", "credential_leak"]
    assert edges[0]["kind"] == "classified_as"
    assert total == 1
    assert more is False
    await storage.close()


async def test_message_attachments(storage: BaseRepository) -> None:
    _src, _gid, _actor, mid, _art = await _seed(storage)
    async with storage.session() as s:
        s.add(
            AttachmentTable(
                message_id=mid,
                kind=AttachmentKind.DOCUMENT,
                mime="application/pdf",
                size_bytes=4096,
                sha256="deadbeef",
                filename="dump.pdf",
                classifier_tier=SensitivityTier.RESTRICTED,
            )
        )
        await s.commit()
    nodes, edges, total, more = await storage.graph_expand(
        src_type="message",
        src_id=mid,
        enrichment="attachments",
        limit=10,
        offset=0,
        want_total=True,
    )
    assert len(nodes) == 1
    assert nodes[0].entity_type == "attachment"
    assert nodes[0].title == "dump.pdf"
    assert nodes[0].fields["tier"] == "restricted"  # effective tier, for the API clearance filter
    assert edges[0]["kind"] == "attached"
    assert total == 1
    assert more is False
    await storage.close()


async def test_message_author_is_single(storage: BaseRepository) -> None:
    _src, _gid, actor, mid, _art = await _seed(storage)
    nodes, edges, total, more = await storage.graph_expand(
        src_type="message", src_id=mid, enrichment="author", limit=10, offset=0, want_total=True
    )
    assert [n.entity_id for n in nodes] == [actor]
    assert edges[0]["kind"] == "authored_by"
    assert total == 1
    assert more is False
    await storage.close()


async def test_counts_and_unknown_guard(storage: BaseRepository) -> None:
    _src, _gid, actor, _mid, _art = await _seed(storage)
    counts = await storage.graph_expand_counts(src_type="actor", src_id=actor)
    assert counts == {
        "messages": 1,
        "artifacts": 1,
        "groups": 1,
        "started": 0,
        "replied_in": 0,
        "incidents": 0,
        "linked": 0,
        "related": 0,
        "source": 1,
    }
    with pytest.raises(ValueError, match="unknown enrichment"):
        await storage.graph_expand(
            src_type="actor", src_id=actor, enrichment="nope", limit=1, offset=0, want_total=False
        )
    # a type with no enrichments -> empty preview, not an error
    assert await storage.graph_expand_counts(src_type="nope", src_id=actor) == {}
    await storage.close()


async def test_persona_actors_and_counts(storage: BaseRepository) -> None:
    src = await storage.upsert_source(kind=SourceKind.FORUM, display_name="f", created_at=_NOW)
    a1, _ = await storage.upsert_actor(
        source_id=src,
        actor_key="p1",
        platform_userid="1",
        handle="h1",
        display_name="h1",
        seen_at=_NOW,
    )
    a2, _ = await storage.upsert_actor(
        source_id=src,
        actor_key="p2",
        platform_userid="2",
        handle="h2",
        display_name="h2",
        seen_at=_NOW,
    )
    persona = await storage.merge_actors_into_persona(a1, a2)
    await storage.put_search_document(entity_type="actor", entity_id=a1, title="h1")
    await storage.put_search_document(entity_type="actor", entity_id=a2, title="h2")
    nodes, edges, total, _ = await storage.graph_expand(
        src_type="persona",
        src_id=persona.id,
        enrichment="actors",
        limit=10,
        offset=0,
        want_total=True,
    )
    assert {n.entity_id for n in nodes} == {a1, a2}
    assert edges[0]["kind"] == "member"
    assert total == 2
    counts = await storage.graph_expand_counts(src_type="persona", src_id=persona.id)
    assert set(counts) == {"actors", "messages", "artifacts", "wallets", "groups"}
    assert counts["actors"] == 2
    await storage.close()
