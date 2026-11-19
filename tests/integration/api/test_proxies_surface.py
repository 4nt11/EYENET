# SPDX-License-Identifier: AGPL-3.0-or-later
"""Integration tests for the proxy-pool surface (v1.2.0).

Covers:
- Pool CRUD (create / list / get / patch / delete empty + non-empty)
- Proxy CRUD (add / list / get / delete / state flip)
- Bulk import + the line parser (scheme:// forms, host:port, host:port:user:pass,
  rejected lines, dedup against existing + against the incoming batch)
- Reveal credential (admin-only, verifies Fernet-at-rest round-trip)
- Identity bind (attach / detach / sticky modes, orphan sticky cleared on detach)
- Scope enforcement (proxy:read vs proxy:write vs proxy:admin + write:identity
  dual-scope on the bind endpoint)

Shares the integration-api fixtures (``client``, ``storage``, ``seed_user``,
``now``). ``proxy:admin`` is a GRANT_ONLY_CAPABILITIES scope, so the test
helper seeds the user THEN explicitly grants it via ``storage.grant_scope``.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from eyenet.contracts.enums import SourceKind, SystemUserRole
from eyenet.storage.repository import BaseRepository

SeedUserFn = Callable[..., Awaitable[UUID]]

pytestmark = pytest.mark.integration


# ---------- helpers ---------------------------------------------------------


def _login(client: TestClient, username: str, password: str) -> str:
    resp = client.post("/v1/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return str(resp.json()["access_token"])


async def _seed_admin_with_proxy_admin(
    storage: BaseRepository, seed_user: SeedUserFn, now: datetime, *, username: str = "op"
) -> str:
    """Seed an ADMIN user and bolt ``proxy:admin`` on top via grant_scope.

    proxy:admin is GRANT_ONLY_CAPABILITIES: not in any role baseline, must be
    explicitly granted. Returns the user's uuid (as str) for convenience; the
    caller logs in with (username, 'pw').
    """
    user_id = await seed_user(username=username, password="pw", role=SystemUserRole.ADMIN)
    await storage.grant_scope(
        user_id=user_id,
        scope="proxy:admin",
        granted_at=now,
        granted_by_user_id=user_id,
    )
    return str(user_id)


async def _seed_source_and_identity(
    storage: BaseRepository, *, kind: SourceKind = SourceKind.TELEGRAM
) -> tuple[str, str]:
    now = datetime.now(tz=UTC)
    src = await storage.upsert_source(kind=kind, display_name=f"{kind.value}:test", created_at=now)
    ident = await storage.create_identity(
        name="pool-tester",
        source_id=src,
        session_path="/var/lib/eyenet/identities/fake.enc",
    )
    return str(src), str(ident.id)


# ---------- pool CRUD ------------------------------------------------------


async def test_pool_create_requires_proxy_admin(
    client: TestClient, storage: BaseRepository, seed_user: SeedUserFn, now: datetime
) -> None:
    """Analyst has proxy:read + proxy:write via baseline but NOT proxy:admin.
    Pool creation is a reshape of operator infra, so the stricter scope gates it."""
    await seed_user(
        username="an",
        password="pw",
        role=SystemUserRole.ANALYST,  # pragma: allowlist secret
    )  # pragma: allowlist secret
    headers = {"Authorization": f"Bearer {_login(client, 'an', 'pw')}"}

    resp = client.post(
        "/v1/proxy-pools",
        json={"name": "shady-1", "kind_hint": "socks5", "description": "test"},
        headers=headers,
    )
    assert resp.status_code == 403, resp.text


async def test_pool_full_crud(
    client: TestClient, storage: BaseRepository, seed_user: SeedUserFn, now: datetime
) -> None:
    await _seed_admin_with_proxy_admin(storage, seed_user, now)
    headers = {"Authorization": f"Bearer {_login(client, 'op', 'pw')}"}

    # create
    create = client.post(
        "/v1/proxy-pools",
        json={"name": "shady-1", "kind_hint": "socks5", "description": "smoke"},
        headers=headers,
    )
    assert create.status_code == 201, create.text
    pool_id = create.json()["id"]
    assert create.json()["name"] == "shady-1"
    assert create.json()["kind_hint"] == "socks5"

    # list (ANALYST sees it too; verifies proxy:read baseline)
    await seed_user(username="an", password="pw", role=SystemUserRole.ANALYST)
    an_headers = {"Authorization": f"Bearer {_login(client, 'an', 'pw')}"}
    lst = client.get("/v1/proxy-pools", headers=an_headers)
    assert lst.status_code == 200
    assert any(p["id"] == pool_id for p in lst.json())

    # get single
    one = client.get(f"/v1/proxy-pools/{pool_id}", headers=an_headers)
    assert one.status_code == 200
    assert one.json()["id"] == pool_id

    # patch (proxy:write on analyst baseline)
    patch = client.patch(
        f"/v1/proxy-pools/{pool_id}",
        json={"description": "renamed"},
        headers=an_headers,
    )
    assert patch.status_code == 200
    assert patch.json()["description"] == "renamed"

    # delete (proxy:admin only; analyst gets 403)
    denied = client.delete(f"/v1/proxy-pools/{pool_id}", headers=an_headers)
    assert denied.status_code == 403

    # delete as admin
    gone = client.delete(f"/v1/proxy-pools/{pool_id}", headers=headers)
    assert gone.status_code == 204
    missing = client.get(f"/v1/proxy-pools/{pool_id}", headers=headers)
    assert missing.status_code == 404


async def test_pool_delete_refuses_non_empty(
    client: TestClient, storage: BaseRepository, seed_user: SeedUserFn, now: datetime
) -> None:
    await _seed_admin_with_proxy_admin(storage, seed_user, now)
    headers = {"Authorization": f"Bearer {_login(client, 'op', 'pw')}"}

    pool_id = client.post(
        "/v1/proxy-pools",
        json={"name": "p"},
        headers=headers,
    ).json()["id"]
    client.post(
        f"/v1/proxy-pools/{pool_id}/proxies",
        json={"kind": "socks5", "host": "1.2.3.4", "port": 1080},  # pragma: allowlist secret
        headers=headers,
    )

    denied = client.delete(f"/v1/proxy-pools/{pool_id}", headers=headers)
    assert denied.status_code == 409  # 'pool is not empty; remove all proxies first'


# ---------- proxy CRUD -----------------------------------------------------


async def test_proxy_crud_secret_masked_on_list(
    client: TestClient, storage: BaseRepository, seed_user: SeedUserFn, now: datetime
) -> None:
    await _seed_admin_with_proxy_admin(storage, seed_user, now)
    headers = {"Authorization": f"Bearer {_login(client, 'op', 'pw')}"}

    pool_id = client.post(
        "/v1/proxy-pools",
        json={"name": "p"},
        headers=headers,
    ).json()["id"]

    # add with secret
    created = client.post(
        f"/v1/proxy-pools/{pool_id}/proxies",
        json={
            "kind": "socks5",
            "host": "1.2.3.4",  # pragma: allowlist secret
            "port": 1080,
            "secret": "user:pw",  # pragma: allowlist secret
            "source": "manual",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    row = created.json()
    assert row["has_secret"] is True
    # Raw secret must NOT be echoed on the standard responses.
    assert "secret" not in row
    assert row["state"] == "active"

    # list
    rows = client.get(f"/v1/proxy-pools/{pool_id}/proxies", headers=headers).json()
    assert len(rows) == 1
    assert rows[0]["has_secret"] is True
    assert "secret" not in rows[0]


async def test_proxy_reveal_requires_proxy_admin(
    client: TestClient, storage: BaseRepository, seed_user: SeedUserFn, now: datetime
) -> None:
    await _seed_admin_with_proxy_admin(storage, seed_user, now)
    admin_headers = {"Authorization": f"Bearer {_login(client, 'op', 'pw')}"}
    await seed_user(username="an", password="pw", role=SystemUserRole.ANALYST)
    an_headers = {"Authorization": f"Bearer {_login(client, 'an', 'pw')}"}

    pool_id = client.post("/v1/proxy-pools", json={"name": "p"}, headers=admin_headers).json()["id"]
    proxy_id = client.post(
        f"/v1/proxy-pools/{pool_id}/proxies",
        json={
            "kind": "http",
            "host": "9.8.7.6",  # pragma: allowlist secret
            "port": 8080,
            "secret": "u:p",
        },  # pragma: allowlist secret
        headers=admin_headers,
    ).json()["id"]

    # Default GET is proxy:read: analyst sees the row but NOT the secret.
    base = client.get(f"/v1/proxies/{proxy_id}", headers=an_headers)
    assert base.status_code == 200
    assert "secret" not in base.json()
    assert base.json()["has_secret"] is True

    # ?reveal=true by analyst: 403 (no proxy:admin)
    denied = client.get(f"/v1/proxies/{proxy_id}?reveal=true", headers=an_headers)
    assert denied.status_code == 403

    # ?reveal=true by admin: credential round-trips Fernet.
    ok = client.get(f"/v1/proxies/{proxy_id}?reveal=true", headers=admin_headers)
    assert ok.status_code == 200
    assert ok.json()["secret"] == "u:p"


async def test_proxy_state_flip_releases_sticky_binding(
    client: TestClient, storage: BaseRepository, seed_user: SeedUserFn, now: datetime
) -> None:
    """Marking a proxy BURNED or DISABLED must clear its sticky
    ``bound_identity_id`` so the pool can lease a fresh proxy next claim.
    This is the operator's kill-switch for a hot-bound proxy that goes dead."""
    await _seed_admin_with_proxy_admin(storage, seed_user, now)
    headers = {"Authorization": f"Bearer {_login(client, 'op', 'pw')}"}
    _src, identity_id = await _seed_source_and_identity(storage)

    pool_id = client.post("/v1/proxy-pools", json={"name": "p"}, headers=headers).json()["id"]
    proxy_id = client.post(
        f"/v1/proxy-pools/{pool_id}/proxies",
        json={"kind": "socks5", "host": "1.1.1.1", "port": 1080},
        headers=headers,
    ).json()["id"]

    # Attach pool + sticky to force a bind when the collector leases.
    client.patch(
        f"/v1/identities/{identity_id}/proxy",
        json={"pool_id": pool_id, "sticky": True},
        headers=headers,
    )
    # Simulate the collector claiming + leasing (storage-side, not through API).
    leased = await storage.lease_proxy_for_identity(
        uuid.UUID(identity_id), source_kind=SourceKind.TELEGRAM
    )
    assert str(leased.id) == proxy_id
    assert str(leased.bound_identity_id) == identity_id

    # Flip to BURNED via API; binding must clear.
    burn = client.post(
        f"/v1/proxies/{proxy_id}/state",
        json={"state": "burned", "reason": "dead on arrival"},
        headers=headers,
    )
    assert burn.status_code == 200
    reread = await storage.get_proxy(uuid.UUID(proxy_id))
    assert reread.state.value == "burned"
    assert reread.bound_identity_id is None


# ---------- bulk import ----------------------------------------------------


async def test_bulk_import_parses_all_shapes(
    client: TestClient, storage: BaseRepository, seed_user: SeedUserFn, now: datetime
) -> None:
    await _seed_admin_with_proxy_admin(storage, seed_user, now)
    headers = {"Authorization": f"Bearer {_login(client, 'op', 'pw')}"}

    pool_id = client.post("/v1/proxy-pools", json={"name": "bulk"}, headers=headers).json()["id"]

    body = {
        "lines": [
            "socks5://1.2.3.4:1080",
            "socks5://u:pw@5.6.7.8:1080",
            "http://9.10.11.12:8080",
            "mtproto://13.14.15.16:443?secret=DEADBEEFCAFE",
            "17.18.19.20:1080",
            "21.22.23.24:1080:user:pass",
            "",  # blank -> ignored
            "# comment",  # comment -> ignored
            "nonsense",  # rejected
            "socks5://1.2.3.4:1080",  # dup against first row
        ],
        "default_kind": "socks5",
        "source": "bulk-test",
    }
    resp = client.post(f"/v1/proxy-pools/{pool_id}/proxies/bulk", json=body, headers=headers)
    assert resp.status_code == 201, resp.text
    result = resp.json()
    # 6 distinct shapes land; 1 is dup-against-batch; 1 is nonsense
    assert result["inserted"] == 6
    assert result["skipped_duplicate"] == 1
    # Rejected surfaces the nonsense line AND the dup line
    joined = " | ".join(result["rejected"])
    assert "nonsense" in joined
    assert "duplicate" in joined.lower()


async def test_bulk_import_requires_proxy_admin(
    client: TestClient, storage: BaseRepository, seed_user: SeedUserFn, now: datetime
) -> None:
    """Analyst has proxy:write (can add single proxies) but NOT proxy:admin
    (needed for bulk, which is the paste-raw-credentials surface)."""
    await _seed_admin_with_proxy_admin(storage, seed_user, now)
    admin_headers = {"Authorization": f"Bearer {_login(client, 'op', 'pw')}"}
    await seed_user(username="an", password="pw", role=SystemUserRole.ANALYST)
    an_headers = {"Authorization": f"Bearer {_login(client, 'an', 'pw')}"}

    pool_id = client.post("/v1/proxy-pools", json={"name": "p"}, headers=admin_headers).json()["id"]
    resp = client.post(
        f"/v1/proxy-pools/{pool_id}/proxies/bulk",
        json={"lines": ["1.2.3.4:1080"], "default_kind": "socks5"},
        headers=an_headers,
    )
    assert resp.status_code == 403


# ---------- identity bind --------------------------------------------------


async def test_identity_bind_roundtrip_and_orphan_sticky_cleared(
    client: TestClient, storage: BaseRepository, seed_user: SeedUserFn, now: datetime
) -> None:
    await _seed_admin_with_proxy_admin(storage, seed_user, now)
    headers = {"Authorization": f"Bearer {_login(client, 'op', 'pw')}"}
    _src, identity_id = await _seed_source_and_identity(storage)

    pool_id = client.post("/v1/proxy-pools", json={"name": "p"}, headers=headers).json()["id"]

    # Attach pool + sticky=yes
    attach = client.patch(
        f"/v1/identities/{identity_id}/proxy",
        json={"pool_id": pool_id, "sticky": True},
        headers=headers,
    )
    assert attach.status_code == 200
    row = attach.json()
    assert row["proxy_pool_id"] == pool_id
    assert row["proxy_sticky"] is True

    # Detach (pool_id=None). Storage must force proxy_sticky back to None so
    # the pair is internally consistent. Sends sticky=True explicitly to
    # prove the forced None wins even against the request.
    detach = client.patch(
        f"/v1/identities/{identity_id}/proxy",
        json={"pool_id": None, "sticky": True},
        headers=headers,
    )
    assert detach.status_code == 200
    assert detach.json()["proxy_pool_id"] is None
    assert detach.json()["proxy_sticky"] is None


async def test_identity_bind_requires_write_identity_too(
    client: TestClient, storage: BaseRepository, seed_user: SeedUserFn, now: datetime
) -> None:
    """proxy:write on the pool side is not enough on its own to modify an
    identity row; write:identity is the second gate. Admin + analyst baselines
    both hold write:identity, so the easiest negative test is a VIEWER with
    proxy:write explicitly granted.
    """
    viewer_id = await seed_user(username="v", password="pw", role=SystemUserRole.VIEWER)
    await storage.grant_scope(
        user_id=viewer_id,
        scope="proxy:write",
        granted_at=now,
        granted_by_user_id=viewer_id,
    )
    headers = {"Authorization": f"Bearer {_login(client, 'v', 'pw')}"}
    _src, identity_id = await _seed_source_and_identity(storage)

    resp = client.patch(
        f"/v1/identities/{identity_id}/proxy",
        json={"pool_id": None, "sticky": None},
        headers=headers,
    )
    assert resp.status_code == 403


async def test_identity_bind_404_on_missing_pool(
    client: TestClient, storage: BaseRepository, seed_user: SeedUserFn, now: datetime
) -> None:
    await _seed_admin_with_proxy_admin(storage, seed_user, now)
    headers = {"Authorization": f"Bearer {_login(client, 'op', 'pw')}"}
    _src, identity_id = await _seed_source_and_identity(storage)
    resp = client.patch(
        f"/v1/identities/{identity_id}/proxy",
        json={"pool_id": str(uuid.uuid4()), "sticky": True},
        headers=headers,
    )
    assert resp.status_code == 404


# ---------- auth boundary --------------------------------------------------


async def test_all_proxy_endpoints_require_auth(client: TestClient) -> None:
    """Spot-check the four surface shapes: pool list, pool create, proxy list,
    proxy state. Unauthenticated hits must 401 before any routing decisions."""
    assert client.get("/v1/proxy-pools").status_code == 401
    assert client.post("/v1/proxy-pools", json={"name": "x"}).status_code == 401
    assert client.get(f"/v1/proxy-pools/{uuid.uuid4()}/proxies").status_code == 401
    resp = client.post(f"/v1/proxies/{uuid.uuid4()}/state", json={"state": "burned"})
    assert resp.status_code == 401
