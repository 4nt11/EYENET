# SPDX-License-Identifier: AGPL-3.0-or-later
"""RelationsMixin + run_relation_builder over a seeded message graph."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from eyenet.contracts.enums import GroupKind, RelationKind, SourceKind
from eyenet.models.message import MessageTable
from eyenet.relations.mentions import run_relation_builder
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


async def _actor(storage: BaseRepository, src: UUID, key: str, handle: str, uid: str) -> UUID:
    return await storage.upsert_actor(
        source_id=src,
        actor_key=key,
        platform_userid=uid,
        handle=handle,
        display_name=handle.lstrip("@").title(),
        seen_at=_NOW,
    )


async def _msg(
    storage: BaseRepository,
    *,
    src: UUID,
    grp: UUID,
    actor: UUID,
    mid: str,
    body: str,
    fwd_origin: UUID | None = None,
    relayed_by: str | None = None,
) -> None:
    ss = {"relayed_by_platform_userid": relayed_by} if relayed_by else {}
    await storage.put_message(
        MessageTable(
            source_id=src,
            group_id=grp,
            actor_id=actor,
            platform_msgid=mid,
            evidence_ref=f"tg:{mid}",
            body=body,
            length_chars=len(body),
            length_words=len(body.split()),
            sent_at_source=_NOW,
            ingested_at=_NOW,
            forward_origin_actor_id=fwd_origin,
            source_specific=ss,
        )
    )


async def _setup(storage: BaseRepository) -> tuple[UUID, UUID, UUID]:
    src = await storage.upsert_source(kind=SourceKind.TELEGRAM, display_name="tg", created_at=_NOW)
    grp = await storage.upsert_group(
        source_id=src, platform_groupid="@g", kind=GroupKind.CHAT, title="g", seen_at=_NOW
    )
    alice = await _actor(storage, src, "tg:alice", "@alice", "111")
    bob = await _actor(storage, src, "tg:bob", "@bob", "222")
    carol = await _actor(storage, src, "tg:carol", "@carol", "333")
    await _msg(storage, src=src, grp=grp, actor=alice, mid="1", body="hey @bob look")
    await _msg(storage, src=src, grp=grp, actor=alice, mid="2", body="@bob and @carol")
    await _msg(storage, src=src, grp=grp, actor=bob, mid="3", body="@alice thanks")
    # A forward: origin author = carol (attribution), relayer = alice (platform 111).
    await _msg(
        storage,
        src=src,
        grp=grp,
        actor=carol,
        mid="4",
        body="leaked db",
        fwd_origin=carol,
        relayed_by="111",
    )
    return alice, bob, carol


async def test_rebuild_materializes_directed_edges(storage: BaseRepository) -> None:
    alice, bob, carol = await _setup(storage)
    n = await run_relation_builder(storage)
    # mentions: alice->bob(x2), alice->carol(x1), bob->alice(x1); forward: alice->carol
    assert n == 4

    out, inb = await storage.actor_relations_for(alice)
    # alice outbound: ->bob (mention x2), ->carol (mention x1), ->carol (forward)
    by = {(r[0], r[3]): r[4] for r in out}  # (other_id, kind) -> count
    assert by[(bob, RelationKind.MENTION)] == 2
    assert by[(carol, RelationKind.MENTION)] == 1
    assert by[(carol, RelationKind.FORWARD)] == 1
    # alice inbound: bob mentioned alice once
    inb_by = {(r[0], r[3]): r[4] for r in inb}
    assert inb_by[(bob, RelationKind.MENTION)] == 1


async def test_read_joins_other_actor_label(storage: BaseRepository) -> None:
    alice, bob, _ = await _setup(storage)
    await run_relation_builder(storage)
    out, _ = await storage.actor_relations_for(alice)
    bob_row = next(r for r in out if r[0] == bob)
    assert bob_row[1] == "@bob"  # handle
    assert bob_row[2] == "Bob"  # display name


async def test_rebuild_is_idempotent(storage: BaseRepository) -> None:
    alice, _, _ = await _setup(storage)
    first = await run_relation_builder(storage)
    second = await run_relation_builder(storage)
    assert first == second
    out, _ = await storage.actor_relations_for(alice)
    # No duplicate edges after a second full-rebuild pass.
    assert len({(r[0], r[3]) for r in out}) == len(out)


async def test_handle_index_and_userid_index(storage: BaseRepository) -> None:
    alice, bob, _ = await _setup(storage)
    h = await storage.handle_to_actor_index()
    assert h["alice"] == alice and h["bob"] == bob
    u = await storage.actor_id_by_platform_userid()
    assert u["111"] == alice


async def test_empty_corpus(storage: BaseRepository) -> None:
    assert await run_relation_builder(storage) == 0
    assert await storage.actor_relations_for(uuid4()) == ([], [])
