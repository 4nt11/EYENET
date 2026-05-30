# SPDX-License-Identifier: AGPL-3.0-or-later
"""Integration tests for the M9.F4 audit read + verify endpoints."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text as sa_text

from eyenet.contracts.enums import SystemUserRole
from eyenet.models._base import new_uuid7
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.integration


def _login(client: TestClient, username: str, password: str) -> str:
    resp = client.post("/v1/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return str(resp.json()["access_token"])


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _append_audit(
    storage: BaseRepository,
    *,
    event: str,
    at: datetime,
    system_user_id: UUID | None = None,
) -> None:
    await storage.append_audit(
        {
            "id": new_uuid7(),
            "event": event,
            "service": "test",
            "instance_id": "t0",
            "system_user_id": system_user_id,
            "subject_kind": "test",
            "subject_id": None,
            "evidence_ref": None,
            "trace_id": None,
            "span_id": None,
            "payload": {},
            "at": at,
        }
    )


async def test_audit_list_filters_by_subject_and_user(
    client: TestClient, storage: BaseRepository, seed_user, now: datetime
) -> None:
    await seed_user(username="a", password="pw", role=SystemUserRole.ADMIN)
    u1 = uuid4()
    await _append_audit(storage, event="eyenet.test.alpha", at=now, system_user_id=u1)
    await _append_audit(storage, event="eyenet.test.alpha", at=now, system_user_id=u1)
    await _append_audit(storage, event="eyenet.test.beta", at=now, system_user_id=uuid4())
    token = _login(client, "a", "pw")

    by_subject = client.get("/v1/audit?subject=eyenet.test.alpha", headers=_auth(token)).json()
    assert len(by_subject["items"]) == 2
    assert {i["subject"] for i in by_subject["items"]} == {"eyenet.test.alpha"}

    by_user = client.get(f"/v1/audit?user={u1}", headers=_auth(token)).json()
    assert {i["user_id"] for i in by_user["items"]} == {str(u1)}


async def test_audit_list_paginates(
    client: TestClient, storage: BaseRepository, seed_user, now: datetime
) -> None:
    await seed_user(username="a", password="pw")
    for _ in range(3):
        await _append_audit(storage, event="eyenet.test.page", at=now)
    token = _login(client, "a", "pw")
    page1 = client.get(
        "/v1/audit?subject=eyenet.test.page&limit=2&include_total=1", headers=_auth(token)
    ).json()
    assert len(page1["items"]) == 2
    assert page1["estimated_total"] == 3
    assert page1["next_cursor"] is not None


async def test_audit_verify_clean_chain(
    client: TestClient, storage: BaseRepository, seed_user, now: datetime
) -> None:
    await seed_user(username="a", password="pw")
    await _append_audit(storage, event="eyenet.test.one", at=now)
    await _append_audit(storage, event="eyenet.test.two", at=now)
    token = _login(client, "a", "pw")
    body = client.get("/v1/audit/verify", headers=_auth(token)).json()
    assert body["verified"] is True
    assert body["first_break"] is None
    assert body["rows_checked"] >= 2


async def test_audit_verify_detects_tamper(
    client: TestClient, storage: BaseRepository, seed_user, now: datetime
) -> None:
    await seed_user(username="a", password="pw")
    await _append_audit(storage, event="eyenet.test.tamper", at=now)
    await _append_audit(storage, event="eyenet.test.tamper2", at=now)
    # Corrupt the earliest row's self_hash directly in audit.db (the only way
    # to defeat tamper-evident storage by design). SQLite-specific setup.
    async with storage.audit_engine.begin() as conn:  # type: ignore[attr-defined]
        await conn.execute(
            sa_text(
                "UPDATE audit_log SET self_hash = :h "
                "WHERE rowid = (SELECT MIN(rowid) FROM audit_log)"
            ),
            {"h": "f" * 64},
        )
    token = _login(client, "a", "pw")
    body = client.get("/v1/audit/verify", headers=_auth(token)).json()
    assert body["verified"] is False
    assert body["first_break"] is not None
    assert body["first_break"]["actual_hash"] == "f" * 64


async def test_audit_forbidden_for_viewer(client: TestClient, seed_user) -> None:
    # VIEWER baseline lacks read:audit.
    await seed_user(username="v", password="pw", role=SystemUserRole.VIEWER)
    token = _login(client, "v", "pw")
    resp = client.get("/v1/audit", headers=_auth(token))
    assert resp.status_code == 403
    assert "read:audit" in resp.json()["detail"]


async def test_audit_requires_auth(client: TestClient) -> None:
    assert client.get("/v1/audit").status_code == 401
