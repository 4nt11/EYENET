# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for eyenet.api.auth._jwt — sign/verify, kid handling, expiry."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from eyenet.api.auth._jwt import (
    ACCESS_TTL,
    AccessClaims,
    JwtError,
    decode_access_token,
    hash_refresh_secret,
    load_signing_keypair,
    load_verifying_keys,
    mint_access_token,
    mint_refresh_secret,
)


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.mark.unit
def test_keypair_is_auto_generated(data_dir: Path) -> None:
    sk = load_signing_keypair(data_dir)
    vks = load_verifying_keys(data_dir)
    assert sk.kid in vks
    signing_pem = data_dir / "jwt" / "signing_key.pem"
    assert signing_pem.exists()
    assert (signing_pem.stat().st_mode & 0o777) == 0o600


@pytest.mark.unit
def test_keypair_is_stable_across_loads(data_dir: Path) -> None:
    first = load_signing_keypair(data_dir)
    second = load_signing_keypair(data_dir)
    assert first.kid == second.kid
    assert first.private_pem == second.private_pem


@pytest.mark.unit
def test_mint_and_decode_round_trip(data_dir: Path) -> None:
    sk = load_signing_keypair(data_dir)
    vks = load_verifying_keys(data_dir)
    user_id = uuid4()
    token, claims = mint_access_token(user_id=user_id, signing_key=sk)
    parsed = decode_access_token(token, verifying_keys=vks)
    assert parsed.user_id == user_id
    assert parsed.jti == claims.jti
    assert isinstance(parsed, AccessClaims)


@pytest.mark.unit
def test_decode_rejects_expired_token(data_dir: Path) -> None:
    sk = load_signing_keypair(data_dir)
    vks = load_verifying_keys(data_dir)
    long_ago = datetime.now(tz=UTC) - ACCESS_TTL - timedelta(minutes=1)
    token, _ = mint_access_token(user_id=uuid4(), signing_key=sk, now=long_ago)
    with pytest.raises(JwtError) as excinfo:
        decode_access_token(token, verifying_keys=vks)
    assert excinfo.value.args[0] == "expired_token"


@pytest.mark.unit
def test_decode_rejects_unknown_kid(data_dir: Path, tmp_path: Path) -> None:
    sk = load_signing_keypair(data_dir)
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    other_vks = load_verifying_keys(other_dir)  # different keypair
    token, _ = mint_access_token(user_id=uuid4(), signing_key=sk)
    # ``other_vks`` doesn't know about ``sk.kid``.
    with pytest.raises(JwtError) as excinfo:
        decode_access_token(token, verifying_keys=other_vks)
    assert excinfo.value.args[0] == "unknown_kid"


@pytest.mark.unit
def test_decode_rejects_tampered_token(data_dir: Path) -> None:
    sk = load_signing_keypair(data_dir)
    vks = load_verifying_keys(data_dir)
    token, _ = mint_access_token(user_id=uuid4(), signing_key=sk)
    # Tamper one character in the payload segment.
    head, payload, sig = token.split(".")
    tampered = f"{head}.{payload[:-1]}A.{sig}"
    with pytest.raises(JwtError):
        decode_access_token(tampered, verifying_keys=vks)


@pytest.mark.unit
def test_decode_rejects_malformed_token(data_dir: Path) -> None:
    vks = load_verifying_keys(data_dir)
    with pytest.raises(JwtError):
        decode_access_token("not.a.jwt", verifying_keys=vks)


@pytest.mark.unit
def test_refresh_secret_round_trip() -> None:
    secret, hex_hash = mint_refresh_secret()
    assert len(hex_hash) == 64
    assert hash_refresh_secret(secret) == hex_hash


@pytest.mark.unit
def test_refresh_secret_is_unique() -> None:
    seen = {mint_refresh_secret()[0] for _ in range(20)}
    assert len(seen) == 20
