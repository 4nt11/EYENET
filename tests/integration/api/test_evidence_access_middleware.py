# SPDX-License-Identifier: AGPL-3.0-or-later
"""Integration tests for the M9.F6 evidence-access audit middleware."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from eyenet.contracts.enums import SourceKind
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.integration

_EVIDENCE = "eyenet.audit.evidence_access"


def _login(client: TestClient, username: str, password: str) -> str:
    resp = client.post("/v1/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return str(resp.json()["access_token"])


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _evidence_rows(storage: BaseRepository) -> list[Any]:
    return [r for r in await storage.all_audit() if r.event == _EVIDENCE]


async def _actor(storage: BaseRepository, now: datetime) -> Any:
    source_id = await storage.upsert_source(
        kind=SourceKind.TELEGRAM, display_name="tg", created_at=now
    )
    return await storage.upsert_actor(
        source_id=source_id,
        actor_key="actor:mw",
        platform_userid="1",
        handle="h",
        display_name="d",
        seen_at=now,
    )


async def test_successful_read_emits_attributed_evidence_row(
    client: TestClient, storage: BaseRepository, seed_user, now: datetime
) -> None:
    user_id = await seed_user(username="a", password="pw")
    actor_id = await _actor(storage, now)
    token = _login(client, "a", "pw")
    resp = client.get(f"/v1/actors/{actor_id}", headers=_auth(token))
    assert resp.status_code == 200, resp.text

    rows = await _evidence_rows(storage)
    assert len(rows) == 1
    row = rows[0]
    assert row.subject_kind == "actor"
    assert str(row.subject_id) == str(actor_id)
    assert row.system_user_id == user_id  # request.state propagation works
    assert row.payload["path"] == f"/v1/actors/{actor_id}"


async def test_audit_failure_withholds_body_with_503(
    client: TestClient, storage: BaseRepository, seed_user, now: datetime
) -> None:
    await seed_user(username="a", password="pw")
    actor_id = await _actor(storage, now)
    token = _login(client, "a", "pw")  # login emits audit BEFORE we break emit

    async def _boom(**_kwargs: Any) -> None:
        raise SQLAlchemyError("audit storage down")

    client.app.state.audit.emit = _boom  # type: ignore[attr-defined]
    resp = client.get(f"/v1/actors/{actor_id}", headers=_auth(token))
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == 503
    assert "evidence withheld" in body["detail"]
    assert body["request_id"]


async def test_non_evidence_path_not_audited(
    client: TestClient, storage: BaseRepository, seed_user
) -> None:
    await seed_user(username="a", password="pw")
    token = _login(client, "a", "pw")
    assert client.get("/v1/auth/me", headers=_auth(token)).status_code == 200
    assert await _evidence_rows(storage) == []


async def test_failed_read_not_audited(
    client: TestClient, storage: BaseRepository, seed_user
) -> None:
    await seed_user(username="a", password="pw")
    token = _login(client, "a", "pw")
    assert client.get(f"/v1/actors/{uuid4()}", headers=_auth(token)).status_code == 404
    assert await _evidence_rows(storage) == []


async def test_list_read_emits_row_without_subject_id(
    client: TestClient, storage: BaseRepository, seed_user
) -> None:
    await seed_user(username="a", password="pw")
    token = _login(client, "a", "pw")
    assert client.get("/v1/linkages", headers=_auth(token)).status_code == 200
    rows = await _evidence_rows(storage)
    assert len(rows) == 1
    assert rows[0].subject_kind == "linkage"
    assert rows[0].subject_id is None
