# SPDX-License-Identifier: AGPL-3.0-or-later
"""PHASE-4 end-to-end: operator signing-key registration via proof-of-possession."""

from __future__ import annotations

import base64
from uuid import UUID

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from httpx import Response

from eyenet.crypto import build_signing_key_challenge_canonical
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.integration


def _login(client: TestClient, username: str, password: str) -> str:
    resp = client.post("/v1/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return str(resp.json()["access_token"])


def _raw_pub(priv: Ed25519PrivateKey) -> bytes:
    return priv.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _challenge(client: TestClient, token: str) -> str:
    resp = client.post(
        "/v1/auth/signing-key/challenge",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    return str(resp.json()["nonce"])


def _register(client: TestClient, token: str, priv: Ed25519PrivateKey, nonce: str) -> Response:
    pub_raw = _raw_pub(priv)
    sig = priv.sign(build_signing_key_challenge_canonical(nonce, pub_raw))
    return client.post(
        "/v1/auth/signing-key",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "public_key_bytes": _b64(pub_raw),
            "challenge_nonce": nonce,
            "challenge_signature": _b64(sig),
        },
    )


async def test_register_happy_path_resolves(
    client: TestClient, seed_user, storage: BaseRepository
) -> None:
    user_id = await seed_user(username="op", password="pw-1")
    token = _login(client, "op", "pw-1")
    priv = Ed25519PrivateKey.generate()
    nonce = _challenge(client, token)

    resp = _register(client, token, priv, nonce)
    assert resp.status_code == 200, resp.text
    fp = resp.json()["fingerprint"]
    assert len(fp) == 16
    resolved = await storage.lookup_key_for_user(user_id, fp)
    assert resolved is not None
    assert resolved[0] == _raw_pub(priv)


async def test_replay_same_nonce_rejected(client: TestClient, seed_user) -> None:
    await seed_user(username="op", password="pw-1")
    token = _login(client, "op", "pw-1")
    priv = Ed25519PrivateKey.generate()
    nonce = _challenge(client, token)

    first = _register(client, token, priv, nonce)
    assert first.status_code == 200, first.text
    # Same nonce again → single-use consume already burned it.
    replay = _register(client, token, priv, nonce)
    assert replay.status_code == 401


async def test_user_a_nonce_with_user_b_token_rejected(
    client: TestClient, seed_user, storage: BaseRepository
) -> None:
    user_a = await seed_user(username="alice", password="pw-a")
    await seed_user(username="bob", password="pw-b")
    token_a = _login(client, "alice", "pw-a")
    token_b = _login(client, "bob", "pw-b")

    nonce_a = _challenge(client, token_a)
    priv = Ed25519PrivateKey.generate()
    # Bob presents Alice's nonce with a valid PoP over his own key.
    resp = _register(client, token_b, priv, nonce_a)
    assert resp.status_code == 401
    # Alice's nonce was not burned by Bob's attempt; nothing registered for A.
    fp = _fp(priv)
    assert await storage.lookup_key_for_user(user_a, fp) is None


async def test_bad_pop_signature_rejected_no_key(
    client: TestClient, seed_user, storage: BaseRepository
) -> None:
    user_id = await seed_user(username="op", password="pw-1")
    token = _login(client, "op", "pw-1")
    priv = Ed25519PrivateKey.generate()
    nonce = _challenge(client, token)
    pub_raw = _raw_pub(priv)
    sig = bytearray(priv.sign(build_signing_key_challenge_canonical(nonce, pub_raw)))
    sig[0] ^= 0x01
    resp = client.post(
        "/v1/auth/signing-key",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "public_key_bytes": _b64(pub_raw),
            "challenge_nonce": nonce,
            "challenge_signature": _b64(bytes(sig)),
        },
    )
    assert resp.status_code == 401
    assert await storage.lookup_key_for_user(user_id, _fp(priv)) is None


async def test_malformed_pubkey_is_422_not_500(client: TestClient, seed_user) -> None:
    await seed_user(username="op", password="pw-1")
    token = _login(client, "op", "pw-1")
    nonce = _challenge(client, token)
    resp = client.post(
        "/v1/auth/signing-key",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "public_key_bytes": _b64(b"\x01" * 31),  # 31 bytes → invalid length
            "challenge_nonce": nonce,
            "challenge_signature": _b64(b"\x00" * 64),
        },
    )
    assert resp.status_code == 422, resp.text


async def test_unauthenticated_challenge_is_401(client: TestClient) -> None:
    resp = client.post("/v1/auth/signing-key/challenge")
    assert resp.status_code == 401


async def test_unauthenticated_register_is_401(client: TestClient) -> None:
    resp = client.post(
        "/v1/auth/signing-key",
        json={
            "public_key_bytes": _b64(b"\x01" * 32),
            "challenge_nonce": str(UUID(int=0)),
            "challenge_signature": _b64(b"\x00" * 64),
        },
    )
    assert resp.status_code == 401


async def test_reregister_retires_prior_key(
    client: TestClient, seed_user, storage: BaseRepository
) -> None:
    user_id = await seed_user(username="op", password="pw-1")
    token = _login(client, "op", "pw-1")

    priv1 = Ed25519PrivateKey.generate()
    fp1 = _register(client, token, priv1, _challenge(client, token)).json()["fingerprint"]

    priv2 = Ed25519PrivateKey.generate()
    fp2 = _register(client, token, priv2, _challenge(client, token)).json()["fingerprint"]

    assert fp1 != fp2
    # New key is the active one.
    active = await storage.active_signing_key_for(user_id)
    assert active == _raw_pub(priv2)
    # Old key still RESOLVABLE (retired, not deleted).
    old = await storage.lookup_key_for_user(user_id, fp1)
    assert old is not None
    assert old[1] is True  # retired flag


async def test_register_emits_audit(client: TestClient, seed_user, storage: BaseRepository) -> None:
    await seed_user(username="op", password="pw-1")
    token = _login(client, "op", "pw-1")
    priv = Ed25519PrivateKey.generate()
    _register(client, token, priv, _challenge(client, token))
    rows = await storage.all_audit()
    events = [r.event for r in rows]
    assert "eyenet.audit.auth.signing_key_registered" in events


def _fp(priv: Ed25519PrivateKey) -> str:
    from eyenet.crypto import fingerprint

    return fingerprint(priv.public_key())
