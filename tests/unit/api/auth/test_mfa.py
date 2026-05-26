"""Unit tests for the TOTP helpers in ``eyenet.api.auth._mfa``."""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pyotp
import pytest

from eyenet.api.auth._mfa import (
    ISSUER,
    generate_secret,
    provisioning_uri,
    verify_code,
)


@pytest.mark.unit
def test_generate_secret_is_base32_and_32_chars() -> None:
    secret = generate_secret()
    assert len(secret) == 32
    # base32 must decode without padding when un-stripped
    base64.b32decode(secret + "=" * (-len(secret) % 8))


@pytest.mark.unit
def test_generate_secret_is_unique() -> None:
    assert generate_secret() != generate_secret()


@pytest.mark.unit
def test_provisioning_uri_shape() -> None:
    secret = generate_secret()
    uri = provisioning_uri(secret_b32=secret, username="anti")
    parsed = urlparse(uri)
    assert parsed.scheme == "otpauth"
    assert parsed.netloc == "totp"
    assert "anti" in parsed.path
    assert ISSUER in parsed.path
    params = parse_qs(parsed.query)
    assert params["secret"] == [secret]
    assert params["issuer"] == [ISSUER]
    # pyotp omits digits/period from the URI when they match the defaults
    # (6 digits, 30s). The provisioning_uri contract elsewhere asserts the
    # values via the TOTP class, not the URI string.


@pytest.mark.unit
def test_verify_code_round_trip() -> None:
    secret = generate_secret()
    now = datetime(2026, 5, 26, 12, 0, 0, tzinfo=UTC)
    code = pyotp.TOTP(secret).at(now)
    assert verify_code(secret_b32=secret, code=code, now=now) is True


@pytest.mark.unit
def test_verify_code_rejects_wrong_code() -> None:
    secret = generate_secret()
    now = datetime(2026, 5, 26, 12, 0, 0, tzinfo=UTC)
    assert verify_code(secret_b32=secret, code="000000", now=now) is False


@pytest.mark.unit
def test_verify_code_rejects_malformed() -> None:
    secret = generate_secret()
    now = datetime(2026, 5, 26, 12, 0, 0, tzinfo=UTC)
    assert verify_code(secret_b32=secret, code="abcdef", now=now) is False
    assert verify_code(secret_b32=secret, code="12345", now=now) is False
    assert verify_code(secret_b32=secret, code="1234567", now=now) is False


@pytest.mark.unit
def test_verify_code_accepts_previous_step() -> None:
    # ±1 step tolerance per RFC 6238 §5.2 — accommodates clock drift.
    secret = generate_secret()
    now = datetime(2026, 5, 26, 12, 0, 0, tzinfo=UTC)
    earlier_code = pyotp.TOTP(secret).at(now - timedelta(seconds=30))
    assert verify_code(secret_b32=secret, code=earlier_code, now=now) is True


@pytest.mark.unit
def test_verify_code_rejects_outside_window() -> None:
    secret = generate_secret()
    now = datetime(2026, 5, 26, 12, 0, 0, tzinfo=UTC)
    way_old = pyotp.TOTP(secret).at(now - timedelta(minutes=5))
    assert verify_code(secret_b32=secret, code=way_old, now=now) is False
