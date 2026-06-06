# SPDX-License-Identifier: AGPL-3.0-or-later
"""ASGI integration tests for the /v1/cases CRUD group (Slice B, §4.10).

Exercises real routing + RequireScope (which the direct-call unit tests bypass)
and serialization round-trips. Storage is seeded BEFORE the first client call to
avoid the shared in-memory aiosqlite MissingGreenlet trap.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from eyenet.contracts.enums import SystemUserRole

pytestmark = pytest.mark.integration

_REASON = "documented for the alpha investigation"


def _login(client: TestClient, username: str, password: str) -> str:
    resp = client.post("/v1/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return str(resp.json()["access_token"])


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_cases_crud_round_trip(client: TestClient, seed_user) -> None:
    await seed_user(username="ana", password="pw", role=SystemUserRole.ANALYST)
    token = _login(client, "ana", "pw")
    h = _auth(token)

    # create
    created = client.post(
        "/v1/cases", json={"title": "Operation Alpha", "description": "d"}, headers=h
    )
    assert created.status_code == 200, created.text
    case_id = created.json()["case_id"]
    assert created.json()["status"] == "open"
    assert created.json()["collaborator_count"] == 1  # creator auto-owner

    # get (creator is a collaborator → visible)
    got = client.get(f"/v1/cases/{case_id}", headers=h)
    assert got.status_code == 200, got.text
    assert got.json()["case_id"] == case_id

    # list (collaborator-scoped visibility → sees own case)
    listed = client.get("/v1/cases?include_total=1", headers=h)
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["estimated_total"] == 1
    assert [c["case_id"] for c in body["items"]] == [case_id]

    # add a member, then list members
    add = client.post(
        f"/v1/cases/{case_id}/members",
        json={"subject_kind": "observation", "subject_id": str(uuid4()), "add_reason": _REASON},
        headers=h,
    )
    assert add.status_code == 200, add.text
    members = client.get(f"/v1/cases/{case_id}/members", headers=h)
    assert members.status_code == 200, members.text
    assert members.json()["estimated_total"] == 1

    # close
    closed = client.post(f"/v1/cases/{case_id}/close", json={"close_reason": _REASON}, headers=h)
    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "closed"


async def test_cases_viewer_forbidden(client: TestClient, seed_user) -> None:
    # VIEWER baseline lacks read:cases AND write:cases.
    await seed_user(username="v", password="pw", role=SystemUserRole.VIEWER)
    h = _auth(_login(client, "v", "pw"))
    assert client.get("/v1/cases", headers=h).status_code == 403
    assert client.post("/v1/cases", json={"title": "Nope"}, headers=h).status_code == 403


async def test_cases_collaborator_add_requires_admin_case(client: TestClient, seed_user) -> None:
    # ADMIN baseline has write:cases but NOT admin:case (grant-only), so the
    # collaborator-management endpoint is forbidden without an explicit grant.
    await seed_user(username="adm", password="pw", role=SystemUserRole.ADMIN)
    h = _auth(_login(client, "adm", "pw"))
    case_id = client.post("/v1/cases", json={"title": "Op Bravo"}, headers=h).json()["case_id"]
    resp = client.post(
        f"/v1/cases/{case_id}/collaborators",
        json={"user_id": str(uuid4()), "role_on_case": "analyst"},
        headers=h,
    )
    assert resp.status_code == 403, resp.text
