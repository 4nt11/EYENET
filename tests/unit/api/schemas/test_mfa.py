"""Shape tests for MFA wire schemas (M9.A3)."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from pydantic import TypeAdapter, ValidationError as PydanticValidationError

from eyenet.api.v1.schemas import (
    LoginResponse,
    MfaDisableRequest,
    MfaEnrollResponse,
    MfaLoginChallenge,
    MfaLoginVerifyRequest,
    MfaVerifyEnrollRequest,
    TokenPair,
)

pytestmark = pytest.mark.contract


_SECRET = "JBSWY3DPEHPK3PXP"
_CODE = "123456"


def test_mfa_enroll_response_happy() -> None:
    resp = MfaEnrollResponse(
        provisioning_uri="otpauth://totp/eyenet:anti?secret=" + _SECRET,
        secret_b32=_SECRET,
    )
    assert resp.secret_b32 == _SECRET


def test_mfa_enroll_response_rejects_short_secret() -> None:
    with pytest.raises(PydanticValidationError):
        MfaEnrollResponse(provisioning_uri="otpauth://x", secret_b32="short")


def test_mfa_verify_enroll_request_rejects_non_six_digit_code() -> None:
    for bad in ("12345", "1234567", "abcdef", "12 456"):
        with pytest.raises(PydanticValidationError):
            MfaVerifyEnrollRequest(secret_b32=_SECRET, code=bad)


def test_mfa_verify_enroll_request_accepts_six_digit_code() -> None:
    req = MfaVerifyEnrollRequest(secret_b32=_SECRET, code=_CODE)
    assert req.code == _CODE


def test_mfa_login_verify_request_round_trip() -> None:
    cid = uuid4()
    req = MfaLoginVerifyRequest(mfa_challenge_id=cid, code=_CODE)
    assert req.mfa_challenge_id == cid
    assert req.code == _CODE


def test_mfa_login_verify_request_rejects_non_uuid() -> None:
    with pytest.raises(PydanticValidationError):
        MfaLoginVerifyRequest.model_validate({"mfa_challenge_id": "not-a-uuid", "code": _CODE})


def test_mfa_disable_request_requires_password() -> None:
    with pytest.raises(PydanticValidationError):
        MfaDisableRequest.model_validate({})


def test_mfa_login_challenge_defaults() -> None:
    chall = MfaLoginChallenge(mfa_challenge_id=uuid4())
    assert chall.kind == "mfa_required"
    assert chall.mfa_required is True


def test_login_response_discriminator_dispatch() -> None:
    adapter: TypeAdapter[LoginResponse] = TypeAdapter(LoginResponse)
    cid = uuid4()
    parsed_chall = adapter.validate_python(
        {"kind": "mfa_required", "mfa_required": True, "mfa_challenge_id": str(cid)},
    )
    assert isinstance(parsed_chall, MfaLoginChallenge)
    assert parsed_chall.mfa_challenge_id == cid

    parsed_pair = adapter.validate_python(
        {
            "kind": "token_pair",
            "access_token": "a",
            "access_expires_at": "2026-05-26T12:00:00Z",
            "refresh_token": "r" * 16,
            "refresh_expires_at": "2026-06-25T12:00:00Z",
        },
    )
    assert isinstance(parsed_pair, TokenPair)


def test_login_response_rejects_unknown_kind() -> None:
    adapter: TypeAdapter[LoginResponse] = TypeAdapter(LoginResponse)
    with pytest.raises(PydanticValidationError):
        adapter.validate_python(
            {"kind": "wat", "mfa_challenge_id": str(UUID(int=0))},
        )
