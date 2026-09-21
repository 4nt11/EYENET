# SPDX-License-Identifier: AGPL-3.0-or-later
"""ASGI-level probes: /v1/healthz + /v1/readyz unauthenticated; /v1/system gated.

Never client.stream() here — the sync TestClient buffers infinite SSE bodies
(see feedback_sync_testclient_infinite_sse_oom). These are plain GETs.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


def test_healthz_unauthenticated_ok(client: TestClient) -> None:
    resp = client.get("/v1/healthz")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"status": "ok"}


def test_readyz_unauthenticated_ready(client: TestClient) -> None:
    resp = client.get("/v1/readyz")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ready"
    assert body["components"] == {
        "storage": "up",
        "bus": "up",
        "auth_keys": "up",  # pragma: allowlist secret
    }


def test_system_requires_auth(client: TestClient) -> None:
    resp = client.get("/v1/system")
    assert resp.status_code == 401, resp.text
