# SPDX-License-Identifier: AGPL-3.0-or-later
"""SavedGraphsMixin — investigation_graph CRUD + node placements.

Types against BaseRepository + constructs via get_repository (Rule 2).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 6, 5, tzinfo=UTC)


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


async def test_create_get_list(storage: BaseRepository) -> None:
    user = uuid4()
    gid = await storage.create_investigation_graph(
        name="opA", description="first", created_by_user_id=user, now=_NOW
    )
    got = await storage.get_investigation_graph(gid)
    assert got is not None
    assert got.name == "opA"
    assert got.created_by_user_id == user
    # a second graph for the same user, newer -> sorts first
    await storage.create_investigation_graph(
        name="opB", description=None, created_by_user_id=user, now=_NOW + timedelta(hours=1)
    )
    mine = await storage.list_investigation_graphs(created_by_user_id=user, limit=10)
    assert [g.name for g in mine] == ["opB", "opA"]
    # another user's graphs are not listed
    other = await storage.list_investigation_graphs(created_by_user_id=uuid4(), limit=10)
    assert other == []
    await storage.close()


async def test_update(storage: BaseRepository) -> None:
    user = uuid4()
    gid = await storage.create_investigation_graph(
        name="old", description=None, created_by_user_id=user, now=_NOW
    )
    assert await storage.update_investigation_graph(gid, name="new", now=_NOW + timedelta(hours=1))
    got = await storage.get_investigation_graph(gid)
    assert got is not None
    assert got.name == "new"
    assert got.updated_at > got.created_at
    assert await storage.update_investigation_graph(uuid4(), name="x") is False
    await storage.close()


async def test_replace_nodes_and_delete(storage: BaseRepository) -> None:
    user = uuid4()
    gid = await storage.create_investigation_graph(
        name="g", description=None, created_by_user_id=user, now=_NOW
    )
    a, b = uuid4(), uuid4()
    n = await storage.replace_investigation_graph_nodes(
        gid,
        [
            ("actor", a, 10.0, 20.0, True, ["actor.messages"]),
            ("artifact", b, 30.0, 40.0, False, []),
        ],
        edges=[{"src_id": str(a), "dst_id": str(b), "kind": "uses", "provenance": "derived"}],
        now=_NOW,
    )
    assert n == 2
    # edges persist on the graph row and come back on get
    saved = await storage.get_investigation_graph(gid)
    assert saved is not None
    assert saved.edges == [
        {"src_id": str(a), "dst_id": str(b), "kind": "uses", "provenance": "derived"}
    ]
    nodes = await storage.get_investigation_graph_nodes(gid)
    assert {node.entity_id for node in nodes} == {a, b}
    placed = {node.entity_id: node for node in nodes}
    assert placed[a].x == 10.0
    assert placed[a].pinned is True
    assert placed[a].enrichments_run == ["actor.messages"]
    # replace is a full swap, not an append
    n2 = await storage.replace_investigation_graph_nodes(
        gid, [("actor", a, 11.0, 22.0, False, [])], now=_NOW
    )
    assert n2 == 1
    nodes2 = await storage.get_investigation_graph_nodes(gid)
    assert [node.entity_id for node in nodes2] == [a]
    assert nodes2[0].x == 11.0
    # delete removes graph + its nodes
    assert await storage.delete_investigation_graph(gid) is True
    assert await storage.get_investigation_graph(gid) is None
    assert await storage.get_investigation_graph_nodes(gid) == []
    assert await storage.delete_investigation_graph(gid) is False
    await storage.close()
