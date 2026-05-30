# SPDX-License-Identifier: AGPL-3.0-or-later
"""Integration tests for the M9.F1 actor + persona read endpoints."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from eyenet.contracts.enums import SourceKind, SystemUserRole, ValueKind
from eyenet.contracts.observation import ObservationRow
from eyenet.storage.repository import BaseRepository
from tests._seed import seed_telegram_fixture

pytestmark = pytest.mark.integration


def _login(client: TestClient, username: str, password: str) -> str:
    resp = client.post("/v1/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return str(resp.json()["access_token"])


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _seed_actor(
    storage: BaseRepository,
    now: datetime,
    *,
    actor_key: str,
    handle: str | None = "alice",
):
    source_id = await storage.upsert_source(
        kind=SourceKind.TELEGRAM, display_name="tg", created_at=now
    )
    actor_id = await storage.upsert_actor(
        source_id=source_id,
        actor_key=actor_key,
        platform_userid="42",
        handle=handle,
        display_name="Alice",
        seen_at=now,
    )
    return source_id, actor_id


# ── actors_get ──────────────────────────────────────────────────────────────


async def test_actors_get_returns_detail(
    client: TestClient, storage: BaseRepository, seed_user, now: datetime
) -> None:
    await seed_user(username="a", password="pw", role=SystemUserRole.ADMIN)
    _, actor_id = await _seed_actor(storage, now, actor_key="actor:f1a")
    token = _login(client, "a", "pw")
    resp = client.get(f"/v1/actors/{actor_id}", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["actor_id"] == str(actor_id)
    assert body["primary_handle"] == "alice"
    assert body["platforms"] == [SourceKind.TELEGRAM.value]
    assert body["observation_count"] == 0
    assert body["persona_id"] is None
    assert body["alias_count"] == 0


async def test_actors_get_falls_back_to_platform_userid(
    client: TestClient, storage: BaseRepository, seed_user, now: datetime
) -> None:
    await seed_user(username="a", password="pw")
    _, actor_id = await _seed_actor(storage, now, actor_key="actor:nohandle", handle=None)
    token = _login(client, "a", "pw")
    body = client.get(f"/v1/actors/{actor_id}", headers=_auth(token)).json()
    assert body["primary_handle"] == "42"


async def test_actors_get_unknown_404(client: TestClient, seed_user) -> None:
    await seed_user(username="a", password="pw")
    token = _login(client, "a", "pw")
    resp = client.get(f"/v1/actors/{uuid4()}", headers=_auth(token))
    assert resp.status_code == 404


async def test_actors_get_requires_auth(client: TestClient) -> None:
    assert client.get(f"/v1/actors/{uuid4()}").status_code == 401


# ── actors_observations ──────────────────────────────────────────────────────


async def test_actors_observations_paginates(
    client: TestClient, storage: BaseRepository, seed_user, now: datetime
) -> None:
    await seed_user(username="a", password="pw")
    _, actor_id = await _seed_actor(storage, now, actor_key="actor:obs")
    for i in range(3):
        await storage.put_observation(
            ObservationRow(
                actor_id=actor_id,
                primitive_namespace="lex",
                primitive_name="emoji_rate",
                primitive_version="1",
                value_kind=ValueKind.NUMERIC,
                value_numeric=float(i),
                observed_at=now + timedelta(minutes=i),
                sensor_instance="s0",
            )
        )
    token = _login(client, "a", "pw")
    body = client.get(
        f"/v1/actors/{actor_id}/observations?limit=2&include_total=1", headers=_auth(token)
    ).json()
    assert len(body["items"]) == 2
    assert body["estimated_total"] == 3
    assert body["next_cursor"] is not None
    # newest-first: minute 2 then minute 1 on page 1
    assert body["items"][0]["kind"] == "lex:emoji_rate"
    page2 = client.get(
        f"/v1/actors/{actor_id}/observations?limit=2&cursor={body['next_cursor']}",
        headers=_auth(token),
    ).json()
    assert len(page2["items"]) == 1
    assert page2["next_cursor"] is None


async def test_observations_forbidden_for_viewer(
    client: TestClient, storage: BaseRepository, seed_user, now: datetime
) -> None:
    # VIEWER baseline has read:actors but NOT read:observations.
    await seed_user(username="v", password="pw", role=SystemUserRole.VIEWER)
    _, actor_id = await _seed_actor(storage, now, actor_key="actor:obs2")
    token = _login(client, "v", "pw")
    resp = client.get(f"/v1/actors/{actor_id}/observations", headers=_auth(token))
    assert resp.status_code == 403
    assert "read:observations" in resp.json()["detail"]


# ── actors_timeline ──────────────────────────────────────────────────────────


async def test_actors_timeline_merges_streams(
    client: TestClient, storage: BaseRepository, seed_user, now: datetime
) -> None:
    await seed_user(username="a", password="pw")
    _, _, actor_ids = await seed_telegram_fixture(
        storage,
        [
            {
                "actor_key": "actor:tl",
                "platform_msgid": "1",
                "body": "hello",
                "sent_at_source": now.isoformat(),
            },
            {
                "actor_key": "actor:tl",
                "platform_msgid": "2",
                "body": "world",
                "sent_at_source": (now + timedelta(minutes=5)).isoformat(),
            },
        ],
        now,
    )
    actor_id = actor_ids["actor:tl"]
    await storage.put_observation(
        ObservationRow(
            actor_id=actor_id,
            primitive_namespace="lex",
            primitive_name="x",
            primitive_version="1",
            value_kind=ValueKind.NUMERIC,
            observed_at=now + timedelta(minutes=2),
            sensor_instance="s",
        )
    )
    token = _login(client, "a", "pw")
    body = client.get(
        f"/v1/actors/{actor_id}/timeline?include_total=1", headers=_auth(token)
    ).json()
    kinds = [e["kind"] for e in body["items"]]
    assert kinds.count("message") == 2
    assert kinds.count("observation") == 1
    assert body["estimated_total"] == 3
    timestamps = [e["ts"] for e in body["items"]]
    assert timestamps == sorted(timestamps, reverse=True)


# ── actors_neighbors ─────────────────────────────────────────────────────────


async def test_actors_neighbors_typed_union(
    client: TestClient, storage: BaseRepository, seed_user, now: datetime
) -> None:
    await seed_user(username="a", password="pw")
    source_id = await storage.upsert_source(
        kind=SourceKind.TELEGRAM, display_name="tg", created_at=now
    )
    a = await storage.upsert_actor(
        source_id=source_id,
        actor_key="actor:n1",
        platform_userid="1",
        handle="a",
        display_name="a",
        seen_at=now,
    )
    b = await storage.upsert_actor(
        source_id=source_id,
        actor_key="actor:n2",
        platform_userid="2",
        handle="b",
        display_name="b",
        seen_at=now,
    )
    await storage.upsert_graph_edge(
        "linked_to",
        a,
        b,
        {"state": "confirmed", "method": "stylometry", "score": 0.9, "linkage_id": str(uuid4())},
    )
    await storage.upsert_graph_edge("belongs_to_persona", a, uuid4(), {"since": now.isoformat()})
    token = _login(client, "a", "pw")
    body = client.get(f"/v1/actors/{a}/neighbors?include_total=1", headers=_auth(token)).json()
    assert {e["edge_type"] for e in body["items"]} == {"linked_to", "belongs_to_persona"}
    assert body["estimated_total"] == 2
    linked = next(e for e in body["items"] if e["edge_type"] == "linked_to")
    assert linked["target_id"] == str(b)
    assert linked["attrs"]["method"] == "stylometry"


# ── personas ─────────────────────────────────────────────────────────────────


async def test_personas_get_and_members(
    client: TestClient, storage: BaseRepository, seed_user, now: datetime
) -> None:
    await seed_user(username="a", password="pw")
    source_id = await storage.upsert_source(
        kind=SourceKind.TELEGRAM, display_name="tg", created_at=now
    )
    a = await storage.upsert_actor(
        source_id=source_id,
        actor_key="actor:p1",
        platform_userid="1",
        handle="a",
        display_name="a",
        seen_at=now,
    )
    b = await storage.upsert_actor(
        source_id=source_id,
        actor_key="actor:p2",
        platform_userid="2",
        handle="b",
        display_name="b",
        seen_at=now,
    )
    persona = await storage.merge_actors_into_persona(a, b, uuid4())
    token = _login(client, "a", "pw")

    detail = client.get(f"/v1/personas/{persona.id}", headers=_auth(token))
    assert detail.status_code == 200, detail.text
    dbody = detail.json()
    assert dbody["persona_id"] == str(persona.id)
    assert dbody["member_count"] == 2
    assert dbody["label"].startswith("persona-")

    members = client.get(
        f"/v1/personas/{persona.id}/members?include_total=1", headers=_auth(token)
    ).json()
    assert members["estimated_total"] == 2
    assert {m["actor_id"] for m in members["items"]} == {str(a), str(b)}
    assert all("since" in m for m in members["items"])


async def test_personas_get_unknown_404(client: TestClient, seed_user) -> None:
    await seed_user(username="a", password="pw")
    token = _login(client, "a", "pw")
    assert client.get(f"/v1/personas/{uuid4()}", headers=_auth(token)).status_code == 404
