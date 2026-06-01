# SPDX-License-Identifier: AGPL-3.0-or-later
"""ASGI smoke tests for the Group D discovery surface (M9.D1-D3).

These drive the REAL app through TestClient — routing, auth, scope gates, and
exception handlers that the direct-call unit tests bypass. The scope-denial
(403) and config-redaction proofs only exist here.

Harness rule: all direct ``await storage`` seeding happens BEFORE the first
client call (the in-memory aiosqlite connection is shared across the test loop
and TestClient's loop; interleaving raises MissingGreenlet).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from eyenet.contracts.enums import (
    CandidateState,
    IdentityState,
    MentionKind,
    SourceKind,
    SystemUserRole,
)
from eyenet.models.identity import IdentityTable
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 5, 26, 12, 0, 0, tzinfo=UTC)


def _login(client: TestClient, username: str, password: str) -> str:
    resp = client.post("/v1/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return str(resp.json()["access_token"])


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _seed_source(storage: BaseRepository, name: str) -> UUID:
    return await storage.upsert_source(kind=SourceKind.TELEGRAM, display_name=name, created_at=_NOW)


async def _seed_identity(storage: BaseRepository, source_id: UUID, name: str) -> UUID:
    async with storage.session() as session:
        row = IdentityTable(
            name=name,
            source_id=source_id,
            session_path=f"/tmp/{name}.session",  # noqa: S108 — test stub
            state=IdentityState.AVAILABLE,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row.id


async def _seed_collector(storage: BaseRepository, source_id: UUID, identity_id: UUID) -> UUID:
    row = await storage.create_collector(
        instance_name="collector_seed",
        kind=SourceKind.TELEGRAM,
        source_id=source_id,
        identity_id=identity_id,
        config={"kind": "telegram"},
        created_at=_NOW,
        created_by_user_id=uuid4(),
    )
    return row.id


# --- sources: full lifecycle through the router ---------------------------


async def test_sources_lifecycle_through_router(client: TestClient, seed_user) -> None:
    await seed_user(username="a", password="pw")  # pragma: allowlist secret
    token = _login(client, "a", "pw")

    created = client.post(
        "/v1/sources",
        json={"kind": "telegram", "display_name": "tg:smoke", "notes": "n"},
        headers=_auth(token),
    )
    assert created.status_code == 201, created.text
    source_id = created.json()["source_id"]

    got = client.get(f"/v1/sources/{source_id}", headers=_auth(token))
    assert got.status_code == 200
    assert got.json()["display_name"] == "tg:smoke"

    dom = client.post(
        f"/v1/sources/{source_id}/domains",
        json={"pattern": "smoke.example", "pattern_kind": "exact", "is_primary": True},
        headers=_auth(token),
    )
    assert dom.status_code == 201, dom.text

    # overlapping add → 409 via the SourceDomainOverlapError app handler
    dup = client.post(
        f"/v1/sources/{source_id}/domains",
        json={"pattern": "smoke.example", "pattern_kind": "exact"},
        headers=_auth(token),
    )
    assert dup.status_code == 409, dup.text

    listed = client.get("/v1/sources", headers=_auth(token))
    assert listed.status_code == 200
    assert listed.json()["items"][0]["active_domain_count"] == 1

    bridge = client.get(f"/v1/sources/{source_id}/bridge-summary", headers=_auth(token))
    assert bridge.status_code == 200
    assert bridge.json()["resolved"] == 0


async def test_sources_write_forbidden_for_viewer(client: TestClient, seed_user) -> None:
    # The scope gate (RequireScope -> 403) that direct-call unit tests can't reach.
    await seed_user(
        username="v",
        password="pw",  # pragma: allowlist secret
        role=SystemUserRole.VIEWER,
    )
    token = _login(client, "v", "pw")
    resp = client.post(
        "/v1/sources",
        json={"kind": "telegram", "display_name": "tg:nope"},
        headers=_auth(token),
    )
    assert resp.status_code == 403
    assert "write:sources" in resp.json()["detail"]


# --- collectors: create + start + redaction through the router ------------


async def test_collectors_through_router_redacts_config(
    client: TestClient, seed_user, storage: BaseRepository
) -> None:
    # Seed everything that needs direct storage BEFORE any client call.
    await seed_user(username="a", password="pw")  # pragma: allowlist secret
    source_id = await _seed_source(storage, "tg:col")
    identity_id = await _seed_identity(storage, source_id, "id_smoke")

    token = _login(client, "a", "pw")
    created = client.post(
        "/v1/collectors",
        json={
            "instance_name": "collector_smoke",
            "kind": "telegram",
            "source_id": str(source_id),
            "identity_id": str(identity_id),
            "config": {"kind": "telegram", "telegram_api_hash": "topsecret"},
        },
        headers=_auth(token),
    )
    assert created.status_code == 201, created.text
    collector_id = created.json()["collector_id"]
    # admin has read:collectors but NOT read:collectors_config (grant-only).
    assert "telegram_api_hash" not in created.json()["config"]
    assert created.json()["config"] == {"__redacted__": True, "kind": "telegram"}

    started = client.post(f"/v1/collectors/{collector_id}/start", headers=_auth(token))
    assert started.status_code == 202, started.text
    assert started.json()["desired_state"] == "running"

    health = client.get("/v1/collectors/health", headers=_auth(token))
    assert health.status_code == 200
    assert health.json()["total"] == 1


# --- candidates: list + approve through the router ------------------------


async def test_candidates_approve_through_router(
    client: TestClient, seed_user, storage: BaseRepository
) -> None:
    # Seed all storage state first (test loop), then drive the API (client loop).
    await seed_user(username="a", password="pw")  # pragma: allowlist secret
    source_id = await _seed_source(storage, "tg:cand")
    identity_id = await _seed_identity(storage, source_id, "id_cand")
    collector_id = await _seed_collector(storage, source_id, identity_id)
    candidate, _ = await storage.record_candidate_mention(
        source_id=source_id,
        platform_groupid="g_smoke",
        observed_by_collector_id=collector_id,
        observed_in_group_id=UUID(int=7),
        seed_root_id=None,
        depth_from_root=1,
        mention_evidence_ref="telegram:g_smoke:1",
        mention_kind=MentionKind.USERNAME_MENTION,
        mentioned_at_source=_NOW,
        mentioned_at_ingest=_NOW,
        mentioning_actor_id=UUID(int=8),
    )
    await storage.transition_candidate(candidate_id=candidate.id, to_state=CandidateState.QUEUED)

    token = _login(client, "a", "pw")
    listed = client.get("/v1/candidates?state=queued", headers=_auth(token))
    assert listed.status_code == 200
    assert [c["candidate_id"] for c in listed.json()["items"]] == [str(candidate.id)]

    approved = client.post(
        f"/v1/candidates/{candidate.id}/approve",
        json={"assigned_collector_id": str(collector_id)},
        headers=_auth(token),
    )
    assert approved.status_code == 202, approved.text
    assert approved.json()["state"] == "approved"
    assert all(
        e["result"] == "deferred_to_runtime" for e in approved.json()["eligibility_per_collector"]
    )
