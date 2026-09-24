# SPDX-License-Identifier: AGPL-3.0-or-later
"""Direct-call unit test for GET /v1/actors/{id}/relationships."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from eyenet.api.deps import CurrentUser, ResourceNotFound
from eyenet.api.v1.actors.api_get_relationships import actors_relationships
from eyenet.contracts.enums import GroupKind, RelationKind, SourceKind
from eyenet.models.message import MessageTable
from eyenet.relations.mentions import run_relation_builder
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


async def _seed(storage: BaseRepository) -> tuple[UUID, UUID]:
    src = await storage.upsert_source(kind=SourceKind.TELEGRAM, display_name="tg", created_at=_NOW)
    grp = await storage.upsert_group(
        source_id=src, platform_groupid="@g", kind=GroupKind.CHAT, title="g", seen_at=_NOW
    )
    alice = await storage.upsert_actor(
        source_id=src,
        actor_key="tg:alice",
        platform_userid="111",
        handle="@alice",
        display_name="Alice",
        seen_at=_NOW,
    )
    bob = await storage.upsert_actor(
        source_id=src,
        actor_key="tg:bob",
        platform_userid="222",
        handle="@bob",
        display_name="Bob",
        seen_at=_NOW,
    )
    await storage.put_message(
        MessageTable(
            source_id=src,
            group_id=grp,
            actor_id=alice,
            platform_msgid="1",
            evidence_ref="tg:1",
            body="hi @bob",
            length_chars=7,
            length_words=2,
            sent_at_source=_NOW,
            ingested_at=_NOW,
        )
    )
    await run_relation_builder(storage)
    return alice, bob


async def test_relationships_shape(
    storage: BaseRepository, mkuser: Callable[..., CurrentUser]
) -> None:
    alice, bob = await _seed(storage)
    res = await actors_relationships(alice, mkuser(), storage, 50)
    assert len(res.outbound) == 1
    n = res.outbound[0]
    assert n.actor_id == bob
    assert n.handle == "@bob"
    assert n.kind is RelationKind.MENTION
    assert n.count == 1
    # bob sees alice on the inbound side.
    res_bob = await actors_relationships(bob, mkuser(), storage, 50)
    assert res_bob.inbound[0].actor_id == alice
    assert res_bob.outbound == []


async def test_relationships_unknown_actor_404(
    storage: BaseRepository, mkuser: Callable[..., CurrentUser]
) -> None:
    with pytest.raises(ResourceNotFound):
        await actors_relationships(uuid4(), mkuser(), storage, 50)
