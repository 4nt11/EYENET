# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/openapi.json is read:graph-gated (§12.5, M9.I2).

The built-in anonymous schema route is disabled; the schema is served only to a
caller holding ``read:graph``. The TS client codegen (M9.I4) consumes it with
such a token.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration

SeedUser = Callable[..., Awaitable[UUID]]


def _login(client: TestClient, username: str, password: str) -> str:
    resp = client.post("/v1/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return str(resp.json()["access_token"])


async def test_openapi_schema_requires_read_graph(client: TestClient, seed_user: SeedUser) -> None:
    # Seed before the first client call (MissingGreenlet discipline).
    password = "correct horse battery staple"
    await seed_user(username="op", password=password)  # ADMIN baseline → read:graph

    anon = client.get("/v1/openapi.json")
    assert anon.status_code == 401
    assert anon.headers["content-type"].startswith("application/problem+json")

    token = _login(client, "op", password)
    ok = client.get("/v1/openapi.json", headers={"Authorization": f"Bearer {token}"})
    assert ok.status_code == 200, ok.text
    spec = ok.json()
    assert spec["openapi"].startswith("3.")
    assert "/v1/auth/login" in spec["paths"]
    # The gated route excludes itself from the schema it serves.
    assert "/v1/openapi.json" not in spec["paths"]
