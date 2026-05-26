# SPDX-License-Identifier: AGPL-3.0-or-later
"""End-to-end auth handler flow: login → refresh → logout, with denylist hits."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from eyenet.contracts.enums import SystemUserRole
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.integration


def _login(client: TestClient, username: str, password: str):
    return client.post("/v1/auth/login", json={"username": username, "password": password})


# --- happy paths --------------------------------------------------------


async def test_login_returns_token_pair(
    client: TestClient,
    seed_user,
    storage: BaseRepository,
) -> None:
    user_id = await seed_user(username="op", password="pw-1")
    resp = _login(client, "op", "pw-1")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["token_type"] == "Bearer"
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["access_expires_at"]
    assert body["refresh_expires_at"]
    fetched = await storage.get_system_user_by_id(user_id)
    assert fetched is not None
    assert fetched.last_login_at is not None


async def test_me_with_valid_token(client: TestClient, seed_user) -> None:
    await seed_user(username="op", password="pw-1", role=SystemUserRole.ADMIN)
    pair = _login(client, "op", "pw-1").json()
    me = client.get(
        "/v1/auth/me",
        headers={"Authorization": f"Bearer {pair['access_token']}"},
    )
    assert me.status_code == 200, me.text
    body = me.json()
    assert body["username"] == "op"
    assert body["role"] == "admin"
    assert "admin:tokens" in body["scopes"]


async def test_refresh_rotates_pair(
    client: TestClient,
    seed_user,
    storage: BaseRepository,
) -> None:
    await seed_user(username="op", password="pw-1")
    first = _login(client, "op", "pw-1").json()

    second = client.post(
        "/v1/auth/refresh",
        json={"refresh_token": first["refresh_token"]},
    )
    assert second.status_code == 200, second.text
    new = second.json()
    assert new["refresh_token"] != first["refresh_token"]
    # Old refresh row is now revoked + chained to the new one.
    from eyenet.api.auth import hash_refresh_secret

    old_row = await storage.get_refresh_token_by_hash(hash_refresh_secret(first["refresh_token"]))
    assert old_row is not None
    assert old_row.revoked_at is not None
    assert old_row.replaced_by is not None


async def test_logout_denylists_jti_and_revokes_refresh(
    client: TestClient,
    seed_user,
    storage: BaseRepository,
) -> None:
    await seed_user(username="op", password="pw-1")
    pair = _login(client, "op", "pw-1").json()
    resp = client.post(
        "/v1/auth/logout",
        headers={"Authorization": f"Bearer {pair['access_token']}"},
        json={"refresh_token": pair["refresh_token"]},
    )
    assert resp.status_code == 204

    # Same access token should now bounce off the denylist.
    me = client.get(
        "/v1/auth/me",
        headers={"Authorization": f"Bearer {pair['access_token']}"},
    )
    assert me.status_code == 401

    # Refresh secret can no longer be redeemed.
    refresh_resp = client.post(
        "/v1/auth/refresh",
        json={"refresh_token": pair["refresh_token"]},
    )
    assert refresh_resp.status_code == 401


# --- failure paths ------------------------------------------------------


async def test_login_wrong_password_returns_401(client: TestClient, seed_user) -> None:
    await seed_user(username="op", password="pw-1")
    resp = _login(client, "op", "wrong")
    assert resp.status_code == 401
    body = resp.json()
    assert body["title"] == "Unauthorized"
    assert body["detail"] == "authentication failed"
    # No WWW-Authenticate header — explicit decision.
    assert "www-authenticate" not in {k.lower() for k in resp.headers}


async def test_login_unknown_user_returns_401(client: TestClient) -> None:
    resp = _login(client, "ghost", "pw-1")
    assert resp.status_code == 401


async def test_login_inactive_user_returns_401(client: TestClient, seed_user) -> None:
    await seed_user(username="op", password="pw-1", is_active=False)
    resp = _login(client, "op", "pw-1")
    assert resp.status_code == 401


async def test_refresh_with_revoked_secret_rejected(
    client: TestClient,
    seed_user,
) -> None:
    await seed_user(username="op", password="pw-1")
    first = _login(client, "op", "pw-1").json()
    # First refresh succeeds.
    client.post("/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    # Replay attempt with the now-revoked secret must fail.
    replay = client.post("/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert replay.status_code == 401


async def test_me_without_bearer_is_401(client: TestClient) -> None:
    resp = client.get("/v1/auth/me")
    assert resp.status_code == 401


async def test_me_with_garbage_token_is_401(client: TestClient) -> None:
    resp = client.get("/v1/auth/me", headers={"Authorization": "Bearer not.a.jwt"})
    assert resp.status_code == 401


# --- audit emission -----------------------------------------------------


async def _audit_events(storage: BaseRepository) -> list[str]:
    rows = await storage.all_audit()
    return [r.event for r in rows]


async def test_login_success_emits_audit(
    client: TestClient,
    seed_user,
    storage: BaseRepository,
) -> None:
    await seed_user(username="op", password="pw-1")
    _login(client, "op", "pw-1")
    events = await _audit_events(storage)
    assert "eyenet.audit.auth.login.success" in events


async def test_login_failure_emits_audit(
    client: TestClient,
    seed_user,
    storage: BaseRepository,
) -> None:
    await seed_user(username="op", password="pw-1")
    _login(client, "op", "wrong")
    events = await _audit_events(storage)
    assert "eyenet.audit.auth.login.failure" in events


async def test_logout_emits_audit(
    client: TestClient,
    seed_user,
    storage: BaseRepository,
) -> None:
    await seed_user(username="op", password="pw-1")
    pair = _login(client, "op", "pw-1").json()
    client.post(
        "/v1/auth/logout",
        headers={"Authorization": f"Bearer {pair['access_token']}"},
        json={"refresh_token": pair["refresh_token"]},
    )
    events = await _audit_events(storage)
    assert "eyenet.audit.auth.logout" in events
