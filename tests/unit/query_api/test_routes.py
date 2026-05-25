"""Unit tests for the read-only query API — FastAPI TestClient over seeded SQLite storage."""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from eyenet.contracts._base import _new_uuid7
from eyenet.contracts.attribution import LinkageRow, PersonaRow, ProfileRow
from eyenet.models.graph import GraphEdgeType, GraphNodeType
from eyenet.query_api.app import create_app
from eyenet.storage import SQLiteStorage

_NOW = datetime(2026, 5, 20, 12, 0, 0, tzinfo=UTC)
_ACTOR_A = UUID("00000000-0000-0000-0000-000000000001")
_ACTOR_B = UUID("00000000-0000-0000-0000-000000000002")
_LID = UUID("00000000-0000-0000-0000-000000000099")


@pytest.fixture
def storage() -> SQLiteStorage:
    d = tempfile.mkdtemp()
    return SQLiteStorage(Path(d))


@pytest.fixture
def client(storage: SQLiteStorage) -> TestClient:
    app = create_app(storage)
    return TestClient(app, raise_server_exceptions=True)


def _profile_row(actor_id: UUID, version: int = 1) -> ProfileRow:
    return ProfileRow(
        id=_new_uuid7(),
        actor_id=actor_id,
        version=version,
        is_current=True,
        role_signal=None,
        role_confidence=0.5,
        derived_at=_NOW,
        derived_from_observation_count=1,
    )


# --- healthz ---


@pytest.mark.unit
def test_healthz_returns_ok(client: TestClient) -> None:
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


# --- /actor/{actor_id} ---


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_actor_returns_summary(storage: SQLiteStorage, client: TestClient) -> None:
    row = _profile_row(_ACTOR_A)
    await storage.upsert_current_profile(row)

    resp = client.get(f"/actor/{_ACTOR_A}")
    assert resp.status_code == 200
    data = resp.json()
    assert UUID(data["actor_id"]) == _ACTOR_A


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_actor_includes_persona_id(storage: SQLiteStorage, client: TestClient) -> None:
    row = _profile_row(_ACTOR_A)
    await storage.upsert_current_profile(row)
    persona = cast(
        "PersonaRow", await storage.merge_actors_into_persona(_ACTOR_A, _ACTOR_B, via_linkage_id=_LID)
    )

    resp = client.get(f"/actor/{_ACTOR_A}")
    assert resp.status_code == 200
    data = resp.json()
    assert UUID(data["persona_id"]) == persona.id


@pytest.mark.unit
def test_get_actor_404_when_missing(client: TestClient) -> None:
    resp = client.get(f"/actor/{_ACTOR_A}")
    assert resp.status_code == 404


# --- /actor/{actor_id}/neighbors ---


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_neighbors_returns_edges(storage: SQLiteStorage, client: TestClient) -> None:
    await storage.upsert_graph_edge(
        GraphEdgeType.LINKED_TO, _ACTOR_A, _ACTOR_B, {"state": "proposed"}
    )

    resp = client.get(f"/actor/{_ACTOR_A}/neighbors")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    assert any(UUID(item["neighbor_id"]) == _ACTOR_B for item in data)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_neighbors_empty_when_no_edges(
    storage: SQLiteStorage, client: TestClient
) -> None:
    resp = client.get(f"/actor/{_ACTOR_A}/neighbors")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_neighbors_filter_by_state(storage: SQLiteStorage, client: TestClient) -> None:
    await storage.upsert_graph_edge(
        GraphEdgeType.LINKED_TO, _ACTOR_A, _ACTOR_B, {"state": "proposed"}
    )
    await storage.upsert_graph_edge(
        GraphEdgeType.LINKED_TO,
        _ACTOR_A,
        UUID("00000000-0000-0000-0000-000000000003"),
        {"state": "confirmed"},
    )

    resp = client.get(f"/actor/{_ACTOR_A}/neighbors?state=confirmed")
    assert resp.status_code == 200
    data = resp.json()
    assert all(item["attrs"].get("state") == "confirmed" for item in data)


# --- /persona/{persona_id} ---


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_persona_returns_summary(storage: SQLiteStorage, client: TestClient) -> None:
    persona = cast(
        "PersonaRow", await storage.merge_actors_into_persona(_ACTOR_A, _ACTOR_B, via_linkage_id=_LID)
    )

    resp = client.get(f"/persona/{persona.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert UUID(data["persona_id"]) == persona.id
    assert data["member_count"] == 2


@pytest.mark.unit
def test_get_persona_404_when_missing(client: TestClient) -> None:
    resp = client.get(f"/persona/{UUID('00000000-0000-0000-0000-999999999999')}")
    assert resp.status_code == 404


# --- /linkages ---


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_linkages_returns_rows(storage: SQLiteStorage, client: TestClient) -> None:
    await storage.insert_proposed_linkage(_ACTOR_A, _ACTOR_B, method="m", score=0.9, evidence={})

    resp = client.get("/linkages")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["method"] == "m"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_linkages_empty_when_none(storage: SQLiteStorage, client: TestClient) -> None:
    resp = client.get("/linkages")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_linkages_filter_by_state(storage: SQLiteStorage, client: TestClient) -> None:
    from eyenet.contracts.enums import LinkageState

    row = cast(
        "LinkageRow",
        await storage.insert_proposed_linkage(
            _ACTOR_A, _ACTOR_B, method="m", score=0.9, evidence={}
        ),
    )
    await storage.transition_linkage(row.id, LinkageState.CONFIRMED, decided_by="anti")

    resp = client.get("/linkages?state=confirmed")
    assert resp.status_code == 200
    data = resp.json()
    assert all(item["state"] == "confirmed" for item in data)


# --- /graph/stats ---


@pytest.mark.unit
@pytest.mark.asyncio
async def test_graph_stats_returns_counts(storage: SQLiteStorage, client: TestClient) -> None:
    await storage.upsert_graph_node(GraphNodeType.ACTOR, _ACTOR_A, {})
    await storage.upsert_graph_node(GraphNodeType.ACTOR, _ACTOR_B, {})
    await storage.upsert_graph_edge(GraphEdgeType.LINKED_TO, _ACTOR_A, _ACTOR_B, {})

    resp = client.get("/graph/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["actors"] == 2
    assert data["linked_to_edges"] == 1
    assert data["personas"] == 0


@pytest.mark.unit
def test_graph_stats_empty_store(client: TestClient) -> None:
    resp = client.get("/graph/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["actors"] == 0
    assert data["personas"] == 0
