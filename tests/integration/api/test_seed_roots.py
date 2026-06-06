# SPDX-License-Identifier: AGPL-3.0-or-later
"""ASGI integration tests for the D4 seed-roots endpoints (Slice C, §4.12)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from eyenet.contracts.enums import SystemUserRole

pytestmark = pytest.mark.integration


def _login(client: TestClient, username: str, password: str) -> str:
    resp = client.post("/v1/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return str(resp.json()["access_token"])


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_seed_roots_get_put_round_trip(client: TestClient, seed_user) -> None:
    await seed_user(username="ana", password="pw", role=SystemUserRole.ANALYST)
    h = _auth(_login(client, "ana", "pw"))
    case_id = client.post("/v1/cases", json={"title": "Operation Alpha"}, headers=h).json()[
        "case_id"
    ]

    assert (
        client.get(f"/v1/cases/{case_id}/seed-roots", headers=h).json()["seed_root_group_ids"] == []
    )

    g1, g2 = str(uuid4()), str(uuid4())
    put = client.put(
        f"/v1/cases/{case_id}/seed-roots",
        json={"seed_root_group_ids": [g1, g2]},
        headers=h,
    )
    assert put.status_code == 200, put.text
    assert set(put.json()["seed_root_group_ids"]) == {g1, g2}

    got = client.get(f"/v1/cases/{case_id}/seed-roots", headers=h)
    assert set(got.json()["seed_root_group_ids"]) == {g1, g2}


async def test_seed_roots_promote_requires_admin_case(client: TestClient, seed_user) -> None:
    # ANALYST has write:cases but not admin:case → promote is forbidden.
    await seed_user(username="ana", password="pw", role=SystemUserRole.ANALYST)
    h = _auth(_login(client, "ana", "pw"))
    case_id = client.post("/v1/cases", json={"title": "Operation Bravo"}, headers=h).json()[
        "case_id"
    ]
    resp = client.post(f"/v1/cases/{case_id}/seed-roots/{uuid4()}", headers=h)
    assert resp.status_code == 403, resp.text


async def test_seed_roots_viewer_forbidden(client: TestClient, seed_user) -> None:
    await seed_user(username="v", password="pw", role=SystemUserRole.VIEWER)
    h = _auth(_login(client, "v", "pw"))
    assert client.get(f"/v1/cases/{uuid4()}/seed-roots", headers=h).status_code == 403
