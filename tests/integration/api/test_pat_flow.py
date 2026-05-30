# SPDX-License-Identifier: AGPL-3.0-or-later
"""End-to-end PAT flow: mint → use → list → revoke, plus the guardrails (M9.A4)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from eyenet.contracts.enums import SystemUserRole

pytestmark = pytest.mark.integration


def _login(client: TestClient, username: str, password: str) -> str:
    resp = client.post("/v1/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return str(resp.json()["access_token"])


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _mint(client: TestClient, access: str, *, name: str, scopes: list[str]) -> dict:
    resp = client.post(
        "/v1/auth/tokens",
        json={"name": name, "scopes": scopes},
        headers=_bearer(access),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# --- core DoD: mint → use → list → revoke → reuse fails ------------------


async def test_mint_use_list_revoke_round_trip(client: TestClient, seed_user) -> None:
    await seed_user(username="op", password="pw-1", role=SystemUserRole.ADMIN)
    access = _login(client, "op", "pw-1")

    minted = _mint(client, access, name="scrape", scopes=["read:metrics"])
    assert minted["secret"].startswith("eyenet_pat_")
    assert minted["prefix"] and "secret" not in {k for k in minted if k == "hash"}
    pat = minted["secret"]
    token_id = minted["token_id"]

    # The PAT authenticates like a JWT — same principal, FROZEN to its scopes.
    me = client.get("/v1/auth/me", headers=_bearer(pat))
    assert me.status_code == 200, me.text
    assert me.json()["username"] == "op"
    assert me.json()["scopes"] == ["read:metrics"]  # narrowed, not admin baseline

    # List shows the token without the secret, last_used_at now populated.
    listing = client.get("/v1/auth/tokens", headers=_bearer(access))
    assert listing.status_code == 200, listing.text
    items = listing.json()["items"]
    assert len(items) == 1
    assert items[0]["token_id"] == token_id
    assert "secret" not in items[0]
    assert items[0]["last_used_at"] is not None

    # Revoke, then the PAT no longer authenticates.
    revoke = client.delete(f"/v1/auth/tokens/{token_id}", headers=_bearer(access))
    assert revoke.status_code == 204, revoke.text
    reuse = client.get("/v1/auth/me", headers=_bearer(pat))
    assert reuse.status_code == 401


# --- guardrails ----------------------------------------------------------


async def test_mint_rejects_scope_escalation(client: TestClient, seed_user) -> None:
    # A viewer cannot mint a PAT carrying scopes it does not hold.
    await seed_user(username="v", password="pw-1", role=SystemUserRole.VIEWER)
    access = _login(client, "v", "pw-1")
    resp = client.post(
        "/v1/auth/tokens",
        json={"name": "nope", "scopes": ["admin:tokens"]},
        headers=_bearer(access),
    )
    assert resp.status_code == 422, resp.text


async def test_revoke_other_users_token_no_oracle(client: TestClient, seed_user) -> None:
    await seed_user(username="admin", password="pw-1", role=SystemUserRole.ADMIN)
    await seed_user(username="viewer", password="pw-2", role=SystemUserRole.VIEWER)
    admin_access = _login(client, "admin", "pw-1")
    viewer_access = _login(client, "viewer", "pw-2")

    admin_pat = _mint(client, admin_access, name="a", scopes=["read:metrics"])
    viewer_pat = _mint(client, viewer_access, name="v", scopes=["read:actors"])

    # Viewer (no admin:tokens) cannot see/revoke the admin's token → 404, no oracle.
    forbidden = client.delete(
        f"/v1/auth/tokens/{admin_pat['token_id']}",
        headers=_bearer(viewer_access),
    )
    assert forbidden.status_code == 404, forbidden.text

    # Admin (admin:tokens) can revoke the viewer's token.
    allowed = client.delete(
        f"/v1/auth/tokens/{viewer_pat['token_id']}",
        headers=_bearer(admin_access),
    )
    assert allowed.status_code == 204, allowed.text


async def test_revoke_missing_token_is_404(client: TestClient, seed_user) -> None:
    await seed_user(username="op", password="pw-1", role=SystemUserRole.ADMIN)
    access = _login(client, "op", "pw-1")
    resp = client.delete(
        "/v1/auth/tokens/00000000-0000-7000-8000-000000000000",
        headers=_bearer(access),
    )
    assert resp.status_code == 404, resp.text


async def test_pat_cannot_logout(client: TestClient, seed_user) -> None:
    await seed_user(username="op", password="pw-1", role=SystemUserRole.ADMIN)
    access = _login(client, "op", "pw-1")
    pat = _mint(client, access, name="scrape", scopes=["read:metrics"])["secret"]
    resp = client.post("/v1/auth/logout", json={}, headers=_bearer(pat))
    assert resp.status_code == 401, resp.text


async def test_tampered_pat_secret_rejected(client: TestClient, seed_user) -> None:
    await seed_user(username="op", password="pw-1", role=SystemUserRole.ADMIN)
    access = _login(client, "op", "pw-1")
    pat = _mint(client, access, name="scrape", scopes=["read:metrics"])["secret"]
    # Flip the final char of the secret segment.
    tampered = pat[:-1] + ("a" if pat[-1] != "a" else "b")
    resp = client.get("/v1/auth/me", headers=_bearer(tampered))
    assert resp.status_code == 401, resp.text
