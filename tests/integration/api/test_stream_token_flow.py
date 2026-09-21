# SPDX-License-Identifier: AGPL-3.0-or-later
"""End-to-end stream-token flow: mint → use on an SSE endpoint, plus the
guardrails — scope gating at mint and token-type isolation (M9.A5)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from eyenet.api.auth import load_signing_keypair, mint_stream_token
from eyenet.contracts.enums import SystemUserRole

pytestmark = pytest.mark.integration


def _login(client: TestClient, username: str, password: str) -> str:
    resp = client.post("/v1/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return str(resp.json()["access_token"])


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _mint_stream(client: TestClient, access: str, *, topics: list[str]):
    return client.post(
        "/v1/auth/stream-token",
        json={"topics": topics},
        headers=_bearer(access),
    )


# --- core DoD: mint → use on an SSE endpoint --------------------------------


async def test_mint_then_use_on_stream_endpoint(client: TestClient, seed_user) -> None:
    await seed_user(username="op", password="pw-1", role=SystemUserRole.ADMIN)
    access = _login(client, "op", "pw-1")

    resp = _mint_stream(
        client,
        access,
        topics=[
            "attribution.linkage",
            "attribution.persona",
            "eyenet.audit",
            "eyenet.control",
        ],
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    token = body["stream_token"]
    assert token  # a non-empty bearer string
    assert set(body["topics"]) == {
        "attribution.linkage",
        "attribution.persona",
        "eyenet.audit",
        "eyenet.control",
    }
    expires_at = datetime.fromisoformat(body["expires_at"])
    assert expires_at <= datetime.now(tz=UTC) + timedelta(minutes=15, seconds=5)

    # NB: we do NOT open the live stream here. The sync starlette TestClient runs
    # the ASGI app to completion before client.stream() returns, so an infinite
    # SSE generator hangs the client and buffers heartbeat frames until OOM. The
    # authorized happy path (token accepted → StreamingResponse + text/event-stream)
    # is proven without a socket in tests/unit/api/streaming/test_handlers.py; the
    # 401 rejection directions are proven by the client.get() tests below.


# --- token-type isolation (both directions) ---------------------------------


async def test_access_token_as_stream_query_is_401(client: TestClient, seed_user) -> None:
    await seed_user(username="op", password="pw-1", role=SystemUserRole.ADMIN)
    access = _login(client, "op", "pw-1")
    # An access JWT in ?token= must not authenticate a stream.
    resp = client.get("/v1/stream/all", params={"token": access})
    assert resp.status_code == 401, resp.text


async def test_stream_token_as_bearer_is_401(client: TestClient, seed_user, data_dir: Path) -> None:
    await seed_user(username="op", password="pw-1", role=SystemUserRole.ADMIN)
    access = _login(client, "op", "pw-1")
    stream_token = _mint_stream(client, access, topics=["eyenet.audit"]).json()["stream_token"]
    # A stream token on the Authorization header must not authenticate /me.
    resp = client.get("/v1/auth/me", headers=_bearer(stream_token))
    assert resp.status_code == 401, resp.text


# --- stream-endpoint auth failures ------------------------------------------


async def test_missing_token_is_401(client: TestClient) -> None:
    assert client.get("/v1/stream/all").status_code == 401


async def test_garbage_token_is_401(client: TestClient) -> None:
    assert client.get("/v1/stream/all", params={"token": "not.a.jwt"}).status_code == 401


async def test_expired_stream_token_is_401(client: TestClient, seed_user, data_dir: Path) -> None:
    user_id = await seed_user(username="op", password="pw-1", role=SystemUserRole.ADMIN)
    # Forge an already-expired token with the app's own signing key.
    sk = load_signing_keypair(data_dir)
    long_ago = datetime.now(tz=UTC) - timedelta(hours=1)
    expired, _ = mint_stream_token(
        user_id=user_id,
        topics=["eyenet.audit"],
        ttl=timedelta(minutes=15),
        signing_key=sk,
        now=long_ago,
    )
    resp = client.get("/v1/stream/audit", params={"token": expired})
    assert resp.status_code == 401, resp.text


# --- mint-time scope gate ----------------------------------------------------


async def test_viewer_cannot_mint_any_stream_token(client: TestClient, seed_user) -> None:
    await seed_user(username="v", password="pw-1", role=SystemUserRole.VIEWER)
    access = _login(client, "v", "pw-1")
    resp = _mint_stream(client, access, topics=["attribution.linkage"])
    assert resp.status_code == 403, resp.text


async def test_analyst_denied_audit_and_control(client: TestClient, seed_user) -> None:
    await seed_user(username="a", password="pw-1", role=SystemUserRole.ANALYST)
    access = _login(client, "a", "pw-1")
    # ANALYST baseline carries stream:linkages + stream:personas, NOT audit/control.
    assert _mint_stream(client, access, topics=["eyenet.audit"]).status_code == 403
    assert _mint_stream(client, access, topics=["eyenet.control"]).status_code == 403


async def test_analyst_allowed_linkage_and_persona(client: TestClient, seed_user) -> None:
    await seed_user(username="a", password="pw-1", role=SystemUserRole.ANALYST)
    access = _login(client, "a", "pw-1")
    resp = _mint_stream(client, access, topics=["attribution.linkage", "attribution.persona"])
    assert resp.status_code == 200, resp.text


# --- don't hobble the operator: a PAT may mint a stream token ----------------


async def test_pat_can_mint_stream_token(client: TestClient, seed_user) -> None:
    await seed_user(username="op", password="pw-1", role=SystemUserRole.ADMIN)
    access = _login(client, "op", "pw-1")
    # Mint a PAT carrying just stream:linkages, then use IT to mint a stream token.
    pat = client.post(
        "/v1/auth/tokens",
        json={"name": "ci", "scopes": ["stream:linkages"]},
        headers=_bearer(access),
    ).json()["secret"]
    resp = _mint_stream(client, pat, topics=["attribution.linkage"])
    assert resp.status_code == 200, resp.text
    # ...but only for the scope it holds — escalation to a non-held topic is 403.
    denied = _mint_stream(client, pat, topics=["eyenet.audit"])
    assert denied.status_code == 403, denied.text
