# SPDX-License-Identifier: AGPL-3.0-or-later
"""Integration tests for the M9.F2 linkage read endpoints."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from eyenet.contracts.enums import LinkageState, SystemUserRole
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.integration


def _login(client: TestClient, username: str, password: str) -> str:
    resp = client.post("/v1/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return str(resp.json()["access_token"])


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_linkages_list_paginates_and_filters(
    client: TestClient, storage: BaseRepository, seed_user
) -> None:
    await seed_user(username="a", password="pw", role=SystemUserRole.ANALYST)
    a1, a2, a3 = uuid4(), uuid4(), uuid4()
    l1 = await storage.insert_proposed_linkage(
        a1, a2, "stylometry", 0.8, {"stylometry": {"score": 0.8}}
    )
    await storage.insert_proposed_linkage(a1, a3, "temporal", 0.6, {})
    token = _login(client, "a", "pw")

    full = client.get("/v1/linkages?include_total=1", headers=_auth(token)).json()
    assert full["estimated_total"] == 2
    assert len(full["items"]) == 2

    by_method = client.get("/v1/linkages?method=stylometry", headers=_auth(token)).json()
    assert {i["linkage_id"] for i in by_method["items"]} == {str(l1.id)}


async def test_linkages_list_filter_by_state(
    client: TestClient, storage: BaseRepository, seed_user
) -> None:
    await seed_user(username="a", password="pw")
    l_proposed = await storage.insert_proposed_linkage(uuid4(), uuid4(), "m1", 0.5, {})
    l_conf = await storage.insert_proposed_linkage(uuid4(), uuid4(), "m2", 0.9, {})
    await storage.transition_linkage(l_conf.id, LinkageState.CONFIRMED, "someone")
    token = _login(client, "a", "pw")

    confirmed = client.get("/v1/linkages?state=confirmed", headers=_auth(token)).json()
    assert {i["linkage_id"] for i in confirmed["items"]} == {str(l_conf.id)}
    assert confirmed["items"][0]["state"] == "confirmed"

    proposed = client.get("/v1/linkages?state=proposed", headers=_auth(token)).json()
    assert {i["linkage_id"] for i in proposed["items"]} == {str(l_proposed.id)}


async def test_linkages_get_flattens_evidence(
    client: TestClient, storage: BaseRepository, seed_user
) -> None:
    await seed_user(username="a", password="pw")
    linkage = await storage.insert_proposed_linkage(
        uuid4(),
        uuid4(),
        "stylo",
        0.9,
        {
            "cosine": {"score": 0.9, "dim": 128},
            "malformed": "not-a-dict",
            "scoreless": {"detail": 1},
        },
    )
    token = _login(client, "a", "pw")
    body = client.get(f"/v1/linkages/{linkage.id}", headers=_auth(token)).json()
    assert body["linkage_id"] == str(linkage.id)
    comps = {e["comparator"]: e for e in body["evidence"]}
    # only the well-formed comparator survives the projection
    assert set(comps) == {"cosine"}
    assert comps["cosine"]["score"] == 0.9
    assert comps["cosine"]["detail"] == {"dim": 128}


async def test_linkages_get_unknown_404(client: TestClient, seed_user) -> None:
    await seed_user(username="a", password="pw")
    token = _login(client, "a", "pw")
    assert client.get(f"/v1/linkages/{uuid4()}", headers=_auth(token)).status_code == 404


async def test_linkages_decided_by_resolves_to_uuid(
    client: TestClient, storage: BaseRepository, seed_user
) -> None:
    decider_id = await seed_user(username="decider", password="pw", role=SystemUserRole.ADMIN)
    linkage = await storage.insert_proposed_linkage(uuid4(), uuid4(), "m", 0.5, {})
    await storage.transition_linkage(linkage.id, LinkageState.CONFIRMED, "decider")
    token = _login(client, "decider", "pw")
    body = client.get(f"/v1/linkages/{linkage.id}", headers=_auth(token)).json()
    assert body["state"] == "confirmed"
    assert body["decided_by"] == str(decider_id)


async def test_linkages_requires_auth(client: TestClient) -> None:
    assert client.get("/v1/linkages").status_code == 401
