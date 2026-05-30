# SPDX-License-Identifier: AGPL-3.0-or-later
"""End-to-end MFA flow: enroll → verify-enroll → login (mfa_required) → verify."""

from __future__ import annotations

from datetime import UTC, datetime

import pyotp
import pytest
from fastapi.testclient import TestClient

from eyenet.contracts.enums import SystemUserRole
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.integration

_SEED_SECRET = "JBSWY3DPEHPK3PXP"


def _login(client: TestClient, username: str, password: str):
    return client.post("/v1/auth/login", json={"username": username, "password": password})


def _bearer(client: TestClient, username: str, password: str) -> dict[str, str]:
    pair = _login(client, username, password).json()
    return {"Authorization": f"Bearer {pair['access_token']}"}


# --- Enrollment ---------------------------------------------------------


async def test_enroll_returns_secret_and_uri_without_persisting(
    client: TestClient,
    seed_user,
    storage: BaseRepository,
) -> None:
    user_id = await seed_user(username="op", password="pw-1")
    headers = _bearer(client, "op", "pw-1")

    resp = client.post("/v1/auth/mfa/enroll", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["provisioning_uri"].startswith("otpauth://")
    assert body["secret_b32"]

    credential = await storage.get_credential(user_id)
    assert credential is not None
    assert credential.mfa_secret_encrypted is None


async def test_verify_enroll_persists_encrypted_secret(
    client: TestClient,
    seed_user,
    storage: BaseRepository,
) -> None:
    user_id = await seed_user(username="op", password="pw-1")
    headers = _bearer(client, "op", "pw-1")

    enroll = client.post("/v1/auth/mfa/enroll", headers=headers).json()
    secret = enroll["secret_b32"]
    code = pyotp.TOTP(secret).now()

    resp = client.post(
        "/v1/auth/mfa/verify-enroll",
        headers=headers,
        json={"secret_b32": secret, "code": code},
    )
    assert resp.status_code == 204, resp.text

    credential = await storage.get_credential(user_id)
    assert credential is not None
    assert credential.mfa_secret_encrypted is not None
    # Encrypted blob should NOT be the raw secret.
    assert secret not in credential.mfa_secret_encrypted


async def test_verify_enroll_wrong_code_persists_nothing(
    client: TestClient,
    seed_user,
    storage: BaseRepository,
) -> None:
    user_id = await seed_user(username="op", password="pw-1")
    headers = _bearer(client, "op", "pw-1")
    enroll = client.post("/v1/auth/mfa/enroll", headers=headers).json()
    resp = client.post(
        "/v1/auth/mfa/verify-enroll",
        headers=headers,
        json={"secret_b32": enroll["secret_b32"], "code": "000000"},
    )
    assert resp.status_code == 401
    credential = await storage.get_credential(user_id)
    assert credential is not None
    assert credential.mfa_secret_encrypted is None


# --- Login challenge / verify -------------------------------------------


async def test_login_returns_mfa_challenge_for_enrolled_user(
    client: TestClient,
    seed_user,
) -> None:
    await seed_user(username="op", password="pw-1", mfa_secret_b32=_SEED_SECRET)
    resp = _login(client, "op", "pw-1")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {**body, "kind": "mfa_required", "mfa_required": True}
    assert "mfa_challenge_id" in body
    assert "access_token" not in body


async def test_login_verify_with_correct_code_issues_pair(
    client: TestClient,
    seed_user,
    storage: BaseRepository,
) -> None:
    user_id = await seed_user(username="op", password="pw-1", mfa_secret_b32=_SEED_SECRET)
    chall = _login(client, "op", "pw-1").json()
    code = pyotp.TOTP(_SEED_SECRET).now()
    resp = client.post(
        "/v1/auth/login/verify",
        json={"mfa_challenge_id": chall["mfa_challenge_id"], "code": code},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["kind"] == "token_pair"
    assert body["access_token"]
    # last_login_at bumped via the verify path.
    fetched = await storage.get_system_user_by_id(user_id)
    assert fetched is not None
    assert fetched.last_login_at is not None


async def test_login_verify_replay_rejected(client: TestClient, seed_user) -> None:
    await seed_user(username="op", password="pw-1", mfa_secret_b32=_SEED_SECRET)
    chall = _login(client, "op", "pw-1").json()
    code = pyotp.TOTP(_SEED_SECRET).now()
    first = client.post(
        "/v1/auth/login/verify",
        json={"mfa_challenge_id": chall["mfa_challenge_id"], "code": code},
    )
    assert first.status_code == 200
    second = client.post(
        "/v1/auth/login/verify",
        json={"mfa_challenge_id": chall["mfa_challenge_id"], "code": code},
    )
    assert second.status_code == 401


async def test_login_verify_unknown_challenge_rejected(client: TestClient) -> None:
    resp = client.post(
        "/v1/auth/login/verify",
        json={"mfa_challenge_id": "00000000-0000-0000-0000-000000000000", "code": "123456"},
    )
    assert resp.status_code == 401


async def test_login_verify_lockout_after_five_failures(
    client: TestClient,
    seed_user,
    storage: BaseRepository,
) -> None:
    user_id = await seed_user(username="op", password="pw-1", mfa_secret_b32=_SEED_SECRET)

    for _ in range(5):
        chall = _login(client, "op", "pw-1").json()
        bad = client.post(
            "/v1/auth/login/verify",
            json={"mfa_challenge_id": chall["mfa_challenge_id"], "code": "000000"},
        )
        assert bad.status_code == 401

    # Sixth attempt: even with the CORRECT code, the lockout window rejects.
    chall = _login(client, "op", "pw-1").json()
    correct = pyotp.TOTP(_SEED_SECRET).now()
    locked = client.post(
        "/v1/auth/login/verify",
        json={"mfa_challenge_id": chall["mfa_challenge_id"], "code": correct},
    )
    assert locked.status_code == 401

    # The operator-visible lockout signal is the audit row.
    from datetime import timedelta

    failures = await storage.count_recent_mfa_failures(
        user_id=user_id,
        since=datetime.now(tz=UTC) - timedelta(minutes=15),
    )
    assert failures >= 5


# --- Disable -------------------------------------------------------------


async def test_mfa_disable_with_correct_password_clears_secret(
    client: TestClient,
    seed_user,
    storage: BaseRepository,
) -> None:
    user_id = await seed_user(username="op", password="pw-1", mfa_secret_b32=_SEED_SECRET)

    # Login normally first (with MFA) to get a bearer.
    chall = _login(client, "op", "pw-1").json()
    code = pyotp.TOTP(_SEED_SECRET).now()
    pair = client.post(
        "/v1/auth/login/verify",
        json={"mfa_challenge_id": chall["mfa_challenge_id"], "code": code},
    ).json()
    headers = {"Authorization": f"Bearer {pair['access_token']}"}

    resp = client.request(
        "DELETE",
        "/v1/auth/mfa",
        headers=headers,
        json={"current_password": "pw-1"},
    )
    assert resp.status_code == 204, resp.text

    credential = await storage.get_credential(user_id)
    assert credential is not None
    assert credential.mfa_secret_encrypted is None


async def test_mfa_disable_with_wrong_password_rejected_and_secret_retained(
    client: TestClient,
    seed_user,
    storage: BaseRepository,
) -> None:
    user_id = await seed_user(username="op", password="pw-1", mfa_secret_b32=_SEED_SECRET)
    chall = _login(client, "op", "pw-1").json()
    code = pyotp.TOTP(_SEED_SECRET).now()
    pair = client.post(
        "/v1/auth/login/verify",
        json={"mfa_challenge_id": chall["mfa_challenge_id"], "code": code},
    ).json()
    headers = {"Authorization": f"Bearer {pair['access_token']}"}

    resp = client.request(
        "DELETE",
        "/v1/auth/mfa",
        headers=headers,
        json={"current_password": "wrong"},
    )
    assert resp.status_code == 401

    credential = await storage.get_credential(user_id)
    assert credential is not None
    assert credential.mfa_secret_encrypted is not None


# --- Plain user still works (no MFA) ------------------------------------


async def test_login_for_non_enrolled_user_returns_token_pair(
    client: TestClient,
    seed_user,
) -> None:
    await seed_user(username="plain", password="pw-1", role=SystemUserRole.VIEWER)
    resp = _login(client, "plain", "pw-1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["kind"] == "token_pair"
    assert body["access_token"]
