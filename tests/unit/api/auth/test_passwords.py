# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for eyenet.api.auth._passwords — argon2id wrappers."""

from __future__ import annotations

import pytest

from eyenet.api.auth._passwords import hash_password, verify_password


@pytest.mark.unit
def test_round_trip() -> None:
    hashed = hash_password("hunter2")
    assert verify_password("hunter2", hashed) is True


@pytest.mark.unit
def test_wrong_password_returns_false() -> None:
    hashed = hash_password("hunter2")
    assert verify_password("Hunter2", hashed) is False


@pytest.mark.unit
def test_malformed_hash_returns_false() -> None:
    assert verify_password("anything", "not-a-real-hash") is False


@pytest.mark.unit
def test_hashes_are_salted_distinct_outputs() -> None:
    a = hash_password("hunter2")
    b = hash_password("hunter2")
    assert a != b
    assert verify_password("hunter2", a)
    assert verify_password("hunter2", b)


@pytest.mark.unit
def test_hash_format_is_argon2id() -> None:
    hashed = hash_password("hunter2")
    assert hashed.startswith("$argon2id$")
