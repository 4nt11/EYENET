# SPDX-License-Identifier: AGPL-3.0-or-later
"""SSE authority wiring over the real ASGI app (M9 Group H).

Proves the stream routes enforce topic authority end-to-end (query-param stream
token → handler). What this file deliberately does NOT do is *open* a live 200
stream: the sync starlette ``TestClient`` runs the ASGI app to completion and
buffers the whole body before ``client.stream().__enter__`` returns, so an
infinite SSE generator (live-tail + heartbeat) hangs the client forever and the
buffered heartbeat frames grow without bound (OOMs the runner). That is a
harness limitation, not a bug in the generator.

The happy path (authorized request → ``StreamingResponse`` +
``text/event-stream`` media type) is proven where it can be, without a socket:
``tests/unit/api/streaming/test_handlers.py`` calls the handlers directly, and
``tests/unit/api/streaming/test_sse.py`` drives the generator itself (live
delivery, replay/dedup, heartbeat, backpressure, expiry). A real-server 200
smoke over a live uvicorn belongs in the e2e tier if we ever want it.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from eyenet.contracts.enums import SystemUserRole

pytestmark = pytest.mark.integration


def _login(client: TestClient, username: str, password: str) -> str:
    resp = client.post("/v1/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return str(resp.json()["access_token"])


def _mint(client: TestClient, access: str, topics: list[str]) -> str:
    resp = client.post(
        "/v1/auth/stream-token",
        json={"topics": topics},
        headers={"Authorization": f"Bearer {access}"},
    )
    assert resp.status_code == 200, resp.text
    return str(resp.json()["stream_token"])


async def test_token_topic_not_covering_endpoint_is_401(client: TestClient, seed_user) -> None:
    await seed_user(username="op", password="pw-1", role=SystemUserRole.ADMIN)
    access = _login(client, "op", "pw-1")
    # Minted for linkages only; audit stream must reject.
    token = _mint(client, access, ["attribution.linkage"])
    resp = client.get("/v1/stream/audit", params={"token": token})
    assert resp.status_code == 401, resp.text


async def test_all_rejects_topic_drift(client: TestClient, seed_user) -> None:
    await seed_user(username="op", password="pw-1", role=SystemUserRole.ADMIN)
    access = _login(client, "op", "pw-1")
    token = _mint(client, access, ["attribution.linkage", "eyenet.audit"])

    # Request set (missing a topic) must equal the token's claim → 401.
    drift = client.get("/v1/stream/all", params={"token": token, "topic": ["attribution.linkage"]})
    assert drift.status_code == 401, drift.text
