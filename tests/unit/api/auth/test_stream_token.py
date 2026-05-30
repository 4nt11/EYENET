# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the M9.A5 stream-token crypto in eyenet.api.auth._jwt.

Round-trip, TTL application, and — the load-bearing part — token-type
isolation: an access token must never decode as a stream token, and vice
versa, even though both are signed with the same RS256 keypair.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from eyenet.api.auth._jwt import (
    STREAM_TTL,
    JwtError,
    StreamClaims,
    decode_access_token,
    decode_stream_token,
    load_signing_keypair,
    load_verifying_keys,
    mint_access_token,
    mint_stream_token,
)


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.mark.unit
def test_mint_and_decode_round_trip(data_dir: Path) -> None:
    sk = load_signing_keypair(data_dir)
    vks = load_verifying_keys(data_dir)
    user_id = uuid4()
    topics = ["attribution.linkage", "eyenet.audit"]
    token, claims = mint_stream_token(
        user_id=user_id,
        topics=topics,
        ttl=STREAM_TTL,
        signing_key=sk,
    )
    parsed = decode_stream_token(token, verifying_keys=vks)
    assert isinstance(parsed, StreamClaims)
    assert parsed.user_id == user_id
    assert parsed.topics == tuple(topics)
    assert parsed.jti == claims.jti


@pytest.mark.unit
def test_exp_respects_ttl(data_dir: Path) -> None:
    sk = load_signing_keypair(data_dir)
    now = datetime(2026, 5, 30, 12, 0, 0, tzinfo=UTC)
    _, claims = mint_stream_token(
        user_id=uuid4(),
        topics=["eyenet.control"],
        ttl=timedelta(seconds=120),
        signing_key=sk,
        now=now,
    )
    assert claims.expires_at == now + timedelta(seconds=120)


@pytest.mark.unit
def test_access_token_rejected_as_stream_token(data_dir: Path) -> None:
    # The reverse-isolation half: an access token presented on the SSE
    # query-param path must not authenticate a stream.
    sk = load_signing_keypair(data_dir)
    vks = load_verifying_keys(data_dir)
    access, _ = mint_access_token(user_id=uuid4(), signing_key=sk)
    with pytest.raises(JwtError) as excinfo:
        decode_stream_token(access, verifying_keys=vks)
    assert excinfo.value.args[0] == "wrong_token_type"


@pytest.mark.unit
def test_stream_token_rejected_as_access_token(data_dir: Path) -> None:
    # The forward-isolation half: a stream token on the Authorization header
    # path must not authenticate a normal API request.
    sk = load_signing_keypair(data_dir)
    vks = load_verifying_keys(data_dir)
    stream, _ = mint_stream_token(
        user_id=uuid4(),
        topics=["attribution.persona"],
        ttl=STREAM_TTL,
        signing_key=sk,
    )
    with pytest.raises(JwtError) as excinfo:
        decode_access_token(stream, verifying_keys=vks)
    assert excinfo.value.args[0] == "wrong_token_type"


@pytest.mark.unit
def test_decode_rejects_expired(data_dir: Path) -> None:
    sk = load_signing_keypair(data_dir)
    vks = load_verifying_keys(data_dir)
    long_ago = datetime.now(tz=UTC) - STREAM_TTL - timedelta(minutes=1)
    token, _ = mint_stream_token(
        user_id=uuid4(),
        topics=["eyenet.audit"],
        ttl=STREAM_TTL,
        signing_key=sk,
        now=long_ago,
    )
    with pytest.raises(JwtError) as excinfo:
        decode_stream_token(token, verifying_keys=vks)
    assert excinfo.value.args[0] == "expired_token"


@pytest.mark.unit
def test_decode_rejects_unknown_kid(data_dir: Path, tmp_path: Path) -> None:
    sk = load_signing_keypair(data_dir)
    other = tmp_path / "other"
    other.mkdir()
    other_vks = load_verifying_keys(other)
    token, _ = mint_stream_token(
        user_id=uuid4(),
        topics=["eyenet.audit"],
        ttl=STREAM_TTL,
        signing_key=sk,
    )
    with pytest.raises(JwtError) as excinfo:
        decode_stream_token(token, verifying_keys=other_vks)
    assert excinfo.value.args[0] == "unknown_kid"


@pytest.mark.unit
def test_decode_rejects_tampered(data_dir: Path) -> None:
    sk = load_signing_keypair(data_dir)
    vks = load_verifying_keys(data_dir)
    token, _ = mint_stream_token(
        user_id=uuid4(),
        topics=["eyenet.audit"],
        ttl=STREAM_TTL,
        signing_key=sk,
    )
    head, payload, sig = token.split(".")
    tampered = f"{head}.{payload[:-1]}A.{sig}"
    with pytest.raises(JwtError):
        decode_stream_token(tampered, verifying_keys=vks)


@pytest.mark.unit
def test_decode_rejects_malformed(data_dir: Path) -> None:
    vks = load_verifying_keys(data_dir)
    with pytest.raises(JwtError):
        decode_stream_token("not.a.jwt", verifying_keys=vks)
