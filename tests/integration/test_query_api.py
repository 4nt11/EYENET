"""Integration test: httpx.AsyncClient over seeded SQLiteStorage + FastAPI app."""

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
from eyenet.contracts.enums import LinkageState
from eyenet.models.graph import GraphEdgeType, GraphNodeType
from eyenet.query_api.app import create_app
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

_NOW = datetime(2026, 5, 20, 12, 0, 0, tzinfo=UTC)
_ACTOR_A = UUID("00000000-0000-0000-0000-000000000001")
_ACTOR_B = UUID("00000000-0000-0000-0000-000000000002")
_ACTOR_C = UUID("00000000-0000-0000-0000-000000000003")
_LID = UUID("00000000-0000-0000-0000-000000000099")


@pytest.fixture
def storage() -> BaseRepository:
    d = tempfile.mkdtemp()
    return get_repository(data_dir=Path(d))


@pytest.fixture
def client(storage: BaseRepository) -> TestClient:
    app = create_app(storage)
    return TestClient(app)


def _profile_row(actor_id: UUID) -> ProfileRow:
    return ProfileRow(
        id=_new_uuid7(),
        actor_id=actor_id,
        version=1,
        is_current=True,
        role_signal=None,
        role_confidence=0.7,
        derived_at=_NOW,
        derived_from_observation_count=5,
    )


@pytest.mark.integration
def test_healthz(client: TestClient) -> None:
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


@pytest.mark.integration
@pytest.mark.asyncio
async def test_full_actor_persona_flow(storage: BaseRepository, client: TestClient) -> None:
    """Seed actor profiles + persona, verify all endpoints return coherent data."""

    # Seed profiles
    await storage.upsert_current_profile(_profile_row(_ACTOR_A))
    await storage.upsert_current_profile(_profile_row(_ACTOR_B))

    # Create persona
    persona = cast(
        "PersonaRow", await storage.merge_actors_into_persona(_ACTOR_A, _ACTOR_B, via_linkage_id=_LID)
    )

    # Seed graph
    await storage.upsert_graph_node(GraphNodeType.ACTOR, _ACTOR_A, {"role_signal": None})
    await storage.upsert_graph_node(GraphNodeType.ACTOR, _ACTOR_B, {"role_signal": None})
    await storage.upsert_graph_edge(
        GraphEdgeType.LINKED_TO, _ACTOR_A, _ACTOR_B, {"state": "confirmed"}
    )

    # Seed linkage
    row = cast(
        "LinkageRow",
        await storage.insert_proposed_linkage(
            _ACTOR_A, _ACTOR_B, method="function_word_simhash_hamming", score=0.95, evidence={}
        ),
    )
    await storage.transition_linkage(row.id, LinkageState.CONFIRMED, decided_by="anti")

    # GET /actor/A
    resp = client.get(f"/actor/{_ACTOR_A}")
    assert resp.status_code == 200
    actor_data = resp.json()
    assert UUID(actor_data["actor_id"]) == _ACTOR_A
    assert UUID(actor_data["persona_id"]) == persona.id

    # GET /actor/A/neighbors
    resp = client.get(f"/actor/{_ACTOR_A}/neighbors")
    assert resp.status_code == 200
    neighbors = resp.json()
    neighbor_ids = {UUID(n["neighbor_id"]) for n in neighbors}
    assert _ACTOR_B in neighbor_ids

    # verify persona endpoint
    resp = client.get(f"/persona/{persona.id}")
    assert resp.status_code == 200
    persona_data = resp.json()
    assert persona_data["member_count"] == 2

    # GET /linkages?state=confirmed
    resp = client.get("/linkages?state=confirmed")
    assert resp.status_code == 200
    linkages = resp.json()
    assert len(linkages) == 1
    assert linkages[0]["state"] == "confirmed"

    # GET /graph/stats
    resp = client.get("/graph/stats")
    assert resp.status_code == 200
    stats = resp.json()
    assert stats["actors"] == 2
    assert stats["linked_to_edges"] == 1


@pytest.mark.integration
def test_actor_not_found_returns_404(client: TestClient) -> None:
    resp = client.get(f"/actor/{UUID('00000000-0000-0000-0000-999999999999')}")
    assert resp.status_code == 404


@pytest.mark.integration
def test_persona_not_found_returns_404(client: TestClient) -> None:
    resp = client.get(f"/persona/{UUID('00000000-0000-0000-0000-999999999999')}")
    assert resp.status_code == 404


@pytest.mark.integration
def test_empty_graph_stats(client: TestClient) -> None:
    resp = client.get("/graph/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert all(v == 0 for v in data.values())


@pytest.mark.integration
@pytest.mark.asyncio
async def test_neighbor_edge_type_filter(storage: BaseRepository, client: TestClient) -> None:
    persona_id = UUID("00000000-0000-0000-0000-000000000010")
    await storage.upsert_graph_edge(
        GraphEdgeType.LINKED_TO, _ACTOR_A, _ACTOR_B, {"state": "proposed"}
    )
    await storage.upsert_graph_edge(GraphEdgeType.BELONGS_TO_PERSONA, _ACTOR_A, persona_id, {})

    resp = client.get(f"/actor/{_ACTOR_A}/neighbors?edge_type=linked_to")
    assert resp.status_code == 200
    data = resp.json()
    assert all(item["edge_type"] == "linked_to" for item in data)
