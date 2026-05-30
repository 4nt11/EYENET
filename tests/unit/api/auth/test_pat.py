# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for the PAT crypto helpers in ``eyenet.api.auth._pat`` (M9.A4)."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from eyenet.api.auth._pat import hash_pat, is_pat, load_pat_pepper, mint_pat, parse_pat

_PEPPER = b"\x00" * 32


@pytest.mark.unit
def test_mint_pat_format_and_self_consistency() -> None:
    full, prefix, digest = mint_pat(_PEPPER)
    assert full.startswith("eyenet_pat_")
    assert len(prefix) == 22
    assert len(digest) == 64
    parsed = parse_pat(full)
    assert parsed is not None
    parsed_prefix, secret = parsed
    assert parsed_prefix == prefix
    assert len(secret) == 32
    # The stored digest is exactly HMAC(pepper, secret).
    assert hash_pat(_PEPPER, secret) == digest


@pytest.mark.unit
def test_mint_pat_is_unique() -> None:
    a_full, _, a_hash = mint_pat(_PEPPER)
    b_full, _, b_hash = mint_pat(_PEPPER)
    assert a_full != b_full
    assert a_hash != b_hash


@pytest.mark.unit
@pytest.mark.parametrize(
    "bad",
    [
        "",
        "nope",
        "eyenet_pat_",
        "Bearer abc",
        "eyJhbGciOiJSUzI1NiJ9.payload.sig",  # a JWT
        "eyenet_pat_" + "a" * 22 + "x" + "b" * 32,  # separator not '_'
        "eyenet_pat_" + "a" * 21 + "_" + "b" * 32,  # prefix too short
        "eyenet_pat_" + "a" * 23 + "_" + "b" * 32,  # prefix too long
        "eyenet_pat_" + "a" * 22 + "_" + "b" * 31,  # secret too short
        "eyenet_pat_" + "a" * 22 + "_" + "b" * 33,  # secret too long
    ],
)
def test_parse_pat_rejects_malformed(bad: str) -> None:
    assert parse_pat(bad) is None


@pytest.mark.unit
def test_parse_pat_does_not_split_on_underscore() -> None:
    # The url-safe base64 alphabet includes '_', so a naive split('_') would
    # corrupt a secret containing underscores. Fixed-offset parse must not.
    token = "eyenet_pat_" + "a" * 22 + "_" + "_" * 32
    assert parse_pat(token) == ("a" * 22, "_" * 32)


@pytest.mark.unit
def test_is_pat_triage() -> None:
    assert is_pat("eyenet_pat_whatever")
    assert not is_pat("eyJhbGciOiJSUzI1NiJ9.x.y")


@pytest.mark.unit
def test_hash_pat_deterministic_and_pepper_bound() -> None:
    assert hash_pat(_PEPPER, "secret") == hash_pat(_PEPPER, "secret")
    assert hash_pat(_PEPPER, "secret") != hash_pat(b"\x01" * 32, "secret")
    assert hash_pat(_PEPPER, "a") != hash_pat(_PEPPER, "b")


@pytest.mark.unit
def test_load_pat_pepper_autogen_mode_and_stable(tmp_path: Path) -> None:
    pepper = load_pat_pepper(tmp_path)
    assert isinstance(pepper, bytes)
    assert len(pepper) == 32

    pepper_path = tmp_path / "jwt" / "pat_pepper"
    assert pepper_path.exists()
    assert stat.S_IMODE(pepper_path.stat().st_mode) == 0o600

    # Stable across calls — never regenerated once materialized.
    assert load_pat_pepper(tmp_path) == pepper
