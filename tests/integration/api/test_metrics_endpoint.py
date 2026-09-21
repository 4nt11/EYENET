# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/metrics — dual gate (read:metrics scope + EYENET_API_METRICS_ENABLED).

Metrics must be enabled BEFORE create_app so init_metrics registers the Prometheus
reader, so these build the app in-test rather than using the shared `app` fixture.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from eyenet.api.app import create_app
from eyenet.contracts.enums import SystemUserRole
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.integration


def _login(client: TestClient, username: str, password: str) -> str:
    resp = client.post("/v1/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return str(resp.json()["access_token"])


async def test_metrics_disabled_is_404_even_for_authorized(
    storage: BaseRepository, data_dir: Path, seed_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("EYENET_API_METRICS_ENABLED", raising=False)
    await seed_user(username="op", password="pw-1", role=SystemUserRole.ADMIN)
    with TestClient(create_app(storage=storage, data_dir=data_dir)) as client:
        token = _login(client, "op", "pw-1")
        resp = client.get("/v1/metrics", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 404, resp.text


async def test_metrics_enabled_serves_prometheus_text_no_user_label(
    storage: BaseRepository, data_dir: Path, seed_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EYENET_API_METRICS_ENABLED", "1")
    await seed_user(username="op", password="pw-1", role=SystemUserRole.ADMIN)
    with TestClient(create_app(storage=storage, data_dir=data_dir)) as client:
        token = _login(client, "op", "pw-1")
        resp = client.get("/v1/metrics", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/plain")
    body = resp.text
    # Health gauge is emitted (boot-time set_health), and the cardinality
    # discipline (§11.7.3) holds — no per-user label leaks into exposition.
    assert "eyenet_api_healthy" in body
    assert "user_id" not in body
    # Slice-2 recording flows to exposition: the login above recorded a request
    # metric and an auth-event metric.
    assert "eyenet_api_requests_total" in body
    assert "eyenet_api_auth_events_total" in body


async def test_metrics_viewer_forbidden(
    storage: BaseRepository, data_dir: Path, seed_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EYENET_API_METRICS_ENABLED", "1")
    await seed_user(username="viewer", password="pw-1", role=SystemUserRole.VIEWER)
    with TestClient(create_app(storage=storage, data_dir=data_dir)) as client:
        token = _login(client, "viewer", "pw-1")
        resp = client.get("/v1/metrics", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403, resp.text


async def test_metrics_unauthenticated_401(
    storage: BaseRepository, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EYENET_API_METRICS_ENABLED", "1")
    with TestClient(create_app(storage=storage, data_dir=data_dir)) as client:
        resp = client.get("/v1/metrics")
    assert resp.status_code == 401, resp.text
