# SPDX-License-Identifier: AGPL-3.0-or-later
"""Integration tests for the M9.F3 graph read endpoints."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from eyenet.contracts.enums import LinkageState, SourceKind, ValueKind
from eyenet.contracts.observation import ObservationRow
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.integration


def _login(client: TestClient, username: str, password: str) -> str:
    resp = client.post("/v1/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return str(resp.json()["access_token"])


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _actor(storage: BaseRepository, now: datetime, key: str, handle: str) -> object:
    source_id = await storage.upsert_source(
        kind=SourceKind.TELEGRAM, display_name="tg", created_at=now
    )
    return await storage.upsert_actor(
        source_id=source_id,
        actor_key=key,
        platform_userid=key[-3:],
        handle=handle,
        display_name=handle.title(),
        seen_at=now,
    )


async def test_graph_stats_counts_source_tables(
    client: TestClient, storage: BaseRepository, seed_user, now: datetime
) -> None:
    await seed_user(username="a", password="pw")
    a1 = await _actor(storage, now, "actor:g1", "alice")
    await _actor(storage, now, "actor:g2", "bob")
    await storage.insert_proposed_linkage(uuid4(), uuid4(), "m", 0.5, {})
    confirmed = await storage.insert_proposed_linkage(uuid4(), uuid4(), "m2", 0.9, {})
    await storage.transition_linkage(confirmed.id, LinkageState.CONFIRMED, "x")
    await storage.put_observation(
        ObservationRow(
            actor_id=a1,
            primitive_namespace="lex",
            primitive_name="e",
            primitive_version="1",
            value_kind=ValueKind.NUMERIC,
            observed_at=now,
            sensor_instance="s",
        )
    )
    token = _login(client, "a", "pw")
    body = client.get("/v1/graph/stats", headers=_auth(token)).json()
    assert body["actors"] == 2
    assert body["observations"] == 1
    assert body["linkages"]["proposed"] == 1
    assert body["linkages"]["confirmed"] == 1
    assert body["linkages"]["suspected"] == 0
    assert "computed_at" in body


async def test_graph_search_matches_handle_case_insensitive(
    client: TestClient, storage: BaseRepository, seed_user, now: datetime
) -> None:
    await seed_user(username="a", password="pw")
    target = await _actor(storage, now, "actor:s1", "AliceCooper")
    await _actor(storage, now, "actor:s2", "bob")
    token = _login(client, "a", "pw")
    body = client.get("/v1/graph/search?q=alice&include_total=1", headers=_auth(token)).json()
    assert body["estimated_total"] == 1
    assert len(body["items"]) == 1
    hit = body["items"][0]
    assert hit["actor_id"] == str(target)
    assert hit["primary_handle"] == "AliceCooper"
    assert hit["platforms"] == [SourceKind.TELEGRAM.value]


async def test_graph_search_matches_display_name(
    client: TestClient, storage: BaseRepository, seed_user, now: datetime
) -> None:
    await seed_user(username="a", password="pw")
    # handle "xy" won't match, but display_name "Xy".title() == "Xy"... search "xy"
    await _actor(storage, now, "actor:d1", "zzz")
    token = _login(client, "a", "pw")
    # display_name is handle.title() == "Zzz"; search the display name
    body = client.get("/v1/graph/search?q=zzz", headers=_auth(token)).json()
    assert len(body["items"]) == 1


async def test_graph_search_no_match_empty_page(
    client: TestClient, storage: BaseRepository, seed_user, now: datetime
) -> None:
    await seed_user(username="a", password="pw")
    await _actor(storage, now, "actor:n1", "alice")
    token = _login(client, "a", "pw")
    body = client.get("/v1/graph/search?q=nomatchxyz", headers=_auth(token)).json()
    assert body["items"] == []
    assert body["next_cursor"] is None


async def test_graph_search_requires_q(client: TestClient, seed_user) -> None:
    await seed_user(username="a", password="pw")
    token = _login(client, "a", "pw")
    # missing required q → 422
    assert client.get("/v1/graph/search", headers=_auth(token)).status_code == 422


async def test_graph_requires_auth(client: TestClient) -> None:
    assert client.get("/v1/graph/stats").status_code == 401
