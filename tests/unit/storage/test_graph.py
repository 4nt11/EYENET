"""Unit tests for SQLiteGraphStore — typed node/edge CRUD and edges_by_type filters."""

from __future__ import annotations

from uuid import UUID

import pytest

from eyenet.models.graph import GraphEdgeType, GraphNodeType
from eyenet.storage.repository import BaseRepository
from eyenet.storage.factory import get_repository

_A = UUID("00000000-0000-0000-0000-000000000001")
_B = UUID("00000000-0000-0000-0000-000000000002")
_C = UUID("00000000-0000-0000-0000-000000000003")
_P = UUID("00000000-0000-0000-0000-000000000010")


@pytest.fixture
def store() -> BaseRepository:
    storage = get_repository(in_memory=True)
    return storage


@pytest.mark.unit
@pytest.mark.asyncio
async def test_upsert_node_creates_actor(store: BaseRepository) -> None:
    await store.upsert_graph_node(GraphNodeType.ACTOR, _A, {"role": "bot"})
    stats = await store.graph_stats()
    assert stats["actors"] >= 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_upsert_node_is_idempotent(store: BaseRepository) -> None:
    await store.upsert_graph_node(GraphNodeType.ACTOR, _A, {"role": "bot"})
    await store.upsert_graph_node(GraphNodeType.ACTOR, _A, {"role": "human"})
    stats = await store.graph_stats()
    assert stats["actors"] == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_upsert_node_merges_attrs(store: BaseRepository) -> None:
    await store.upsert_graph_node(GraphNodeType.ACTOR, _A, {"role": "bot"})
    await store.upsert_graph_node(GraphNodeType.ACTOR, _A, {"confidence": 0.9})
    stats = await store.graph_stats()
    assert stats["actors"] == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_upsert_edge_creates_linked_to(store: BaseRepository) -> None:
    await store.upsert_graph_node(GraphNodeType.ACTOR, _A, {})
    await store.upsert_graph_node(GraphNodeType.ACTOR, _B, {})
    await store.upsert_graph_edge(GraphEdgeType.LINKED_TO, _A, _B, {"state": "proposed"})
    stats = await store.graph_stats()
    assert stats["linked_to_edges"] >= 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_upsert_edge_is_idempotent(store: BaseRepository) -> None:
    await store.upsert_graph_edge(GraphEdgeType.LINKED_TO, _A, _B, {"state": "proposed"})
    await store.upsert_graph_edge(GraphEdgeType.LINKED_TO, _A, _B, {"state": "confirmed"})
    stats = await store.graph_stats()
    assert stats["linked_to_edges"] == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_delete_edge_removes_it(store: BaseRepository) -> None:
    await store.upsert_graph_edge(GraphEdgeType.LINKED_TO, _A, _B, {})
    await store.delete_graph_edge(GraphEdgeType.LINKED_TO, _A, _B)
    stats = await store.graph_stats()
    assert stats["linked_to_edges"] == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_delete_edge_noop_when_missing(store: BaseRepository) -> None:
    await store.delete_graph_edge(GraphEdgeType.LINKED_TO, _A, _B)  # should not raise
    stats = await store.graph_stats()
    assert stats["linked_to_edges"] == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_neighbors_returns_connected_actors(store: BaseRepository) -> None:
    await store.upsert_graph_edge(GraphEdgeType.LINKED_TO, _A, _B, {"state": "proposed"})
    await store.upsert_graph_edge(GraphEdgeType.LINKED_TO, _A, _C, {"state": "confirmed"})
    neighbors = await store.graph_neighbors(_A)
    neighbor_ids = {n[0] for n in neighbors}
    assert _B in neighbor_ids
    assert _C in neighbor_ids


@pytest.mark.unit
@pytest.mark.asyncio
async def test_neighbors_filters_by_edge_type(store: BaseRepository) -> None:
    await store.upsert_graph_edge(GraphEdgeType.LINKED_TO, _A, _B, {})
    await store.upsert_graph_edge(GraphEdgeType.BELONGS_TO_PERSONA, _A, _P, {})
    linked = await store.graph_neighbors(_A, edge_type=GraphEdgeType.LINKED_TO)
    assert all(n[1] == GraphEdgeType.LINKED_TO for n in linked)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_edges_by_type_returns_typed_edges(store: BaseRepository) -> None:
    await store.upsert_graph_edge(GraphEdgeType.LINKED_TO, _A, _B, {"state": "proposed"})
    await store.upsert_graph_edge(GraphEdgeType.LINKED_TO, _A, _C, {"state": "confirmed"})
    await store.upsert_graph_edge(GraphEdgeType.BELONGS_TO_PERSONA, _A, _P, {})

    linked = await store.graph_edges_by_type(GraphEdgeType.LINKED_TO)
    assert len(linked) == 2
    assert all(e[0] == _A for e in linked)  # all have src_id == _A


@pytest.mark.unit
@pytest.mark.asyncio
async def test_edges_by_type_filters_by_src(store: BaseRepository) -> None:
    await store.upsert_graph_edge(GraphEdgeType.LINKED_TO, _A, _B, {})
    await store.upsert_graph_edge(GraphEdgeType.LINKED_TO, _B, _C, {})
    edges = await store.graph_edges_by_type(GraphEdgeType.LINKED_TO, src_id=_A)
    assert all(e[0] == _A for e in edges)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_edges_by_type_filters_by_dst(store: BaseRepository) -> None:
    await store.upsert_graph_edge(GraphEdgeType.LINKED_TO, _A, _B, {})
    await store.upsert_graph_edge(GraphEdgeType.LINKED_TO, _C, _B, {})
    edges = await store.graph_edges_by_type(GraphEdgeType.LINKED_TO, dst_id=_B)
    assert all(e[1] == _B for e in edges)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stats_counts_nodes_and_edges(store: BaseRepository) -> None:
    await store.upsert_graph_node(GraphNodeType.ACTOR, _A, {})
    await store.upsert_graph_node(GraphNodeType.PERSONA, _P, {})
    await store.upsert_graph_edge(GraphEdgeType.BELONGS_TO_PERSONA, _A, _P, {})
    stats = await store.graph_stats()
    assert stats["actors"] == 1
    assert stats["personas"] == 1
    assert stats["belongs_to_persona_edges"] == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stats_empty_store(store: BaseRepository) -> None:
    stats = await store.graph_stats()
    assert stats["actors"] == 0
    assert stats["personas"] == 0
    assert stats["linked_to_edges"] == 0
    assert stats["belongs_to_persona_edges"] == 0
