# ruff: noqa: RUF003 — Unicode digit examples are intentional in the pattern docstring
"""MFA-surface schemas (API_PLAN §M9.A3).

Wire shapes for enroll / verify-enroll / login-verify / disable. The
existing :class:`MfaLoginChallenge` in :mod:`schemas.auth` is the 200
body when ``/v1/auth/login`` short-circuits to a second-factor prompt;
it lives there rather than here because it composes into
:data:`LoginResponse`.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import Field

from ._base import ApiSchema

# ASCII-only on purpose. Pydantic v2's Rust regex `\d` matches Unicode
# digit categories (Arabic-Indic ٠–٩, Devanagari ०–९, mathematical bold,
# etc.) — pyotp's internal comparison would still reject them, but a
# defense-in-depth ASCII gate at the schema boundary keeps exotic inputs
# from ever reaching the verifier.
_TOTP_CODE_PATTERN = r"^[0-9]{6}$"
_SECRET_B32_MIN = 16  # 80 bits — RFC 4226 §4 floor
_SECRET_B32_MAX = 128


class MfaEnrollResponse(ApiSchema):
    """200 response from `POST /v1/auth/mfa/enroll`.

    The secret has NOT been persisted yet. The client must echo it back
    in :class:`MfaVerifyEnrollRequest`. Until verify-enroll succeeds, the
    user remains un-enrolled — re-running ``/enroll`` is safe.
    """

    provisioning_uri: str = Field(
        min_length=1,
        max_length=2048,
        description="otpauth:// URI for QR-code rendering by the client.",
    )
    secret_b32: str = Field(
        min_length=_SECRET_B32_MIN,
        max_length=_SECRET_B32_MAX,
        description="Base32-encoded TOTP secret. Echo back in verify-enroll.",
    )


class MfaVerifyEnrollRequest(ApiSchema):
    """Body for `POST /v1/auth/mfa/verify-enroll`."""

    secret_b32: str = Field(min_length=_SECRET_B32_MIN, max_length=_SECRET_B32_MAX)
    code: str = Field(pattern=_TOTP_CODE_PATTERN)


class MfaLoginVerifyRequest(ApiSchema):
    """Body for `POST /v1/auth/login/verify` (challenge_id IS the auth)."""

    mfa_challenge_id: UUID
    code: str = Field(pattern=_TOTP_CODE_PATTERN)


class MfaDisableRequest(ApiSchema):
    """Body for `DELETE /v1/auth/mfa` — primary-factor re-auth required."""

    current_password: str = Field(min_length=1, max_length=1024)


__all__ = [
    "MfaDisableRequest",
    "MfaEnrollResponse",
    "MfaLoginVerifyRequest",
    "MfaVerifyEnrollRequest",
]
