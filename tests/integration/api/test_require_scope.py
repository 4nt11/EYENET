# SPDX-License-Identifier: AGPL-3.0-or-later
"""RequireScope factory — viewer 403, viewer+grant 200, admin 200 from baseline."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from eyenet.api.deps import CurrentUser, RequireScope
from eyenet.contracts.enums import SystemUserRole
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.integration


@pytest.fixture
def gated_app(app: FastAPI) -> FastAPI:
    require_metrics = RequireScope("read:metrics")

    @app.get("/_test/metrics")
    async def metrics_handler(
        current_user: CurrentUser = Depends(require_metrics),  # noqa: B008
    ) -> dict[str, str]:
        return {"user": current_user.username}

    return app


@pytest.fixture
def gated_client(gated_app: FastAPI):
    with TestClient(gated_app) as c:
        yield c


def _login(client: TestClient, username: str, password: str) -> dict[str, str]:
    resp = client.post("/v1/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_viewer_without_grant_is_forbidden(
    gated_client: TestClient,
    seed_user,
) -> None:
    await seed_user(username="v", password="pw", role=SystemUserRole.VIEWER)
    pair = _login(gated_client, "v", "pw")
    resp = gated_client.get(
        "/_test/metrics",
        headers={"Authorization": f"Bearer {pair['access_token']}"},
    )
    assert resp.status_code == 403
    assert "read:metrics" in resp.json()["detail"]


async def test_viewer_with_explicit_grant_is_allowed(
    gated_client: TestClient,
    seed_user,
    storage: BaseRepository,
) -> None:
    user_id = await seed_user(username="v", password="pw", role=SystemUserRole.VIEWER)
    await storage.grant_scope(
        user_id=user_id,
        scope="read:metrics",
        granted_at=datetime.now(tz=UTC),
        granted_by_user_id=uuid4(),
    )
    pair = _login(gated_client, "v", "pw")
    resp = gated_client.get(
        "/_test/metrics",
        headers={"Authorization": f"Bearer {pair['access_token']}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"user": "v"}


async def test_admin_gets_metrics_from_baseline(
    gated_client: TestClient,
    seed_user,
) -> None:
    await seed_user(username="a", password="pw", role=SystemUserRole.ADMIN)
    pair = _login(gated_client, "a", "pw")
    resp = gated_client.get(
        "/_test/metrics",
        headers={"Authorization": f"Bearer {pair['access_token']}"},
    )
    assert resp.status_code == 200, resp.text


async def test_no_bearer_is_401(gated_client: TestClient) -> None:
    resp = gated_client.get("/_test/metrics")
    assert resp.status_code == 401
