# SPDX-License-Identifier: AGPL-3.0-or-later
"""Integration tests for the identity read endpoints (list + detail)."""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from eyenet.contracts.enums import SourceKind, SystemUserRole
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.integration


def _login(client: TestClient, username: str, password: str) -> str:
    resp = client.post("/v1/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return str(resp.json()["access_token"])


async def test_identities_list_and_detail_omit_opsec_fields(
    client: TestClient, storage: BaseRepository, seed_user, now: datetime
) -> None:
    # Seed storage BEFORE the first client call (async ASGI test).
    await seed_user(username="a", password="pw", role=SystemUserRole.ADMIN)
    src = await storage.upsert_source(
        kind=SourceKind.TELEGRAM, display_name="tg:pool", created_at=now
    )
    ident = await storage.create_identity(
        name="pool-01",
        source_id=src,
        session_path="/secret/session.blob",
        proxy_uri="socks5://user:pass@host:1080",
    )

    headers = {"Authorization": f"Bearer {_login(client, 'a', 'pw')}"}

    resp = client.get("/v1/identities", headers=headers)
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert len(items) == 1
    row = items[0]
    assert row["identity_id"] == str(ident.id)
    assert row["name"] == "pool-01"
    assert row["state"] == "available"
    # OPSEC fields must never cross the read surface.
    assert "session_path" not in row
    assert "proxy_uri" not in row

    detail = client.get(f"/v1/identities/{ident.id}", headers=headers)
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["cooldown_seconds"] > 0
    assert "session_path" not in body
    assert "proxy_uri" not in body

    missing = client.get(f"/v1/identities/{uuid.uuid4()}", headers=headers)
    assert missing.status_code == 404


async def test_identities_list_requires_auth(client: TestClient) -> None:
    assert client.get("/v1/identities").status_code == 401
