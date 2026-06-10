"""Auth-surface schemas — login, refresh, logout, me, PATs, stream tokens.

The backing storage tables (`system_user_credential`, `refresh_token`,
`personal_access_token`, `jwt_denylist`) land in M9.1 per API_PLAN §4.1;
until then these schemas declare the wire shape only and `from_domain()`
translators are documented TODOs.

OpenAPI: `contracts/openapi/eyenet.v1.yaml` — Login*, Refresh*, Logout*,
TokenPair, UserMe, PAT*, StreamToken*.
API_PLAN §3.1, §4.
"""

from __future__ import annotations

import base64
import binascii
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, field_validator

from ._base import ApiSchema
from .enums import StreamTopic, SystemUserRole
from .pagination import CursorPage

# PHASE-4 — Ed25519 raw public key is 32 bytes; a detached signature is 64.
_ED25519_PUBLIC_KEY_LEN = 32
_ED25519_SIGNATURE_LEN = 64


def _decode_fixed_b64(value: object, *, expected_len: int, field: str) -> bytes:
    """Decode a base64 string to exactly ``expected_len`` raw bytes.

    Raises ``ValueError`` (→ pydantic 422, never a 500) on a non-string, a
    non-base64 string, or a payload of the wrong decoded length. Used at the
    schema boundary so malformed key/signature material is rejected cleanly
    before the registration logic — defense in depth above the crypto loader's
    own fail-closed guard.
    """
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a base64-encoded string")
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"{field} is not valid base64") from exc
    if len(raw) != expected_len:
        raise ValueError(f"{field} must decode to exactly {expected_len} bytes")
    return raw


class LoginRequest(ApiSchema):
    """Body for `POST /v1/auth/login`."""

    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=1024)


class RefreshRequest(ApiSchema):
    """Body for `POST /v1/auth/refresh`."""

    refresh_token: str = Field(min_length=16, max_length=256)


class LogoutRequest(ApiSchema):
    """Body for `POST /v1/auth/logout` — refresh token is optional.

    When present, the matching refresh row is revoked alongside the
    access JWT denylist write. When omitted, only the access JWT is
    denylisted (use this from a UI that has already discarded the
    refresh secret).
    """

    refresh_token: str | None = Field(default=None, min_length=16, max_length=256)


class TokenPair(ApiSchema):
    """200 response from `/v1/auth/login` (no MFA) or `/v1/auth/login/verify`.

    ``kind`` is the discriminator for :data:`LoginResponse` — additive to
    spec §M9.A2, ignored by clients that don't read it.
    """

    kind: Literal["token_pair"] = "token_pair"
    access_token: str
    access_expires_at: datetime
    refresh_token: str
    refresh_expires_at: datetime
    token_type: Literal["Bearer"] = "Bearer"


class MfaLoginChallenge(ApiSchema):
    """200 response from `/v1/auth/login` when the user is MFA-enrolled.

    Client must follow up with `POST /v1/auth/login/verify` carrying the
    ``mfa_challenge_id`` and the 6-digit TOTP code (API_PLAN §M9.A3).
    """

    kind: Literal["mfa_required"] = "mfa_required"
    mfa_required: Literal[True] = True
    mfa_challenge_id: UUID


LoginResponse = Annotated[TokenPair | MfaLoginChallenge, Field(discriminator="kind")]
"""Discriminated union surface of `POST /v1/auth/login`."""


class UserMe(ApiSchema):
    """Projection of MODELS.md §2.17 SystemUser for `/v1/auth/me`.

    TODO(M9.1): `from_domain(SystemUserTable, scopes: list[str])` once the
    `system_user_scope` join is wired. Scopes are resolved at request time
    from the backing table — never from a JWT claim (API_PLAN §4.2).
    """

    user_id: UUID
    username: str = Field(max_length=128)
    role: SystemUserRole
    scopes: list[str] = Field(
        default_factory=list,
        description="Flat scope strings granted to this user at the moment of the request.",
    )


class PATSummary(ApiSchema):
    """Projection of API_PLAN §4.1 personal_access_token (TBD M9.1 storage).

    TODO(M9.1): `from_domain(PersonalAccessTokenTable)` once the table exists.
    """

    token_id: UUID
    name: str = Field(max_length=128)
    prefix: str = Field(
        max_length=32,
        description=(
            "Plaintext PAT prefix (`<22-char-prefix>`) for display. The secret is never returned."
        ),
    )
    scopes: list[str] = Field(default_factory=list)
    created_at: datetime
    last_used_at: datetime | None = None
    expires_at: datetime | None = None


class PATMintRequest(ApiSchema):
    """Body for `POST /v1/auth/tokens`."""

    name: str = Field(min_length=1, max_length=128)
    scopes: list[str] = Field(min_length=1)
    expires_at: datetime | None = None


class PATMinted(ApiSchema):
    """201 response from `POST /v1/auth/tokens` — `secret` is plaintext ONCE.

    TODO(M9.1): `from_domain(PersonalAccessTokenTable, secret: str)` — the
    one-time secret is provided by the mint flow, never re-read from storage.
    """

    token_id: UUID
    name: str = Field(max_length=128)
    prefix: str = Field(max_length=32)
    scopes: list[str] = Field(default_factory=list)
    secret: str = Field(
        description="Full PAT (`eyenet_pat_<prefix>_<secret>`). Shown ONCE. Never re-displayed.",
    )
    created_at: datetime
    expires_at: datetime | None = None


class StreamTokenRequest(ApiSchema):
    """Body for `POST /v1/auth/stream-token` — browser SSE fallback."""

    topics: list[StreamTopic] = Field(min_length=1, max_length=16)
    ttl_seconds: int = Field(default=900, ge=60, le=900)


class StreamTokenMinted(ApiSchema):
    """200 response from `POST /v1/auth/stream-token`."""

    stream_token: str
    expires_at: datetime
    topics: list[StreamTopic]


class CursorPagePATSummary(CursorPage[PATSummary]):
    """200 page response for `GET /v1/auth/tokens`."""


class SigningKeyChallengeResponse(ApiSchema):
    """200 response from `POST /v1/auth/signing-key/challenge` (PHASE-4).

    The operator signs `EYENET-SIGNING-KEY-CHALLENGE-v1(nonce, public_key)`
    with the candidate private key and submits the signature to
    `POST /v1/auth/signing-key` before `expires_at` (60s lifetime).
    """

    nonce: UUID
    expires_at: datetime


class SigningKeyRegisterRequest(ApiSchema):
    """Body for `POST /v1/auth/signing-key` (PHASE-4 self-service registration).

    ``public_key_bytes`` and ``challenge_signature`` arrive base64-encoded and
    are decoded + length-validated at this boundary (Ed25519: 32-byte key,
    64-byte signature). Malformed material is rejected as 422 here — it never
    reaches the registration logic as a 500.
    """

    public_key_bytes: bytes
    challenge_nonce: UUID
    challenge_signature: bytes

    @field_validator("public_key_bytes", mode="before")
    @classmethod
    def _decode_public_key(cls, value: object) -> bytes:
        return _decode_fixed_b64(
            value, expected_len=_ED25519_PUBLIC_KEY_LEN, field="public_key_bytes"
        )

    @field_validator("challenge_signature", mode="before")
    @classmethod
    def _decode_signature(cls, value: object) -> bytes:
        return _decode_fixed_b64(
            value, expected_len=_ED25519_SIGNATURE_LEN, field="challenge_signature"
        )


class SigningKeyRegisterResponse(ApiSchema):
    """200 response from `POST /v1/auth/signing-key` (PHASE-4).

    ``fingerprint`` is the 16-hex ``kid`` of the now-active key; any prior
    active key for this operator has been retired (one-active invariant).
    """

    fingerprint: str = Field(min_length=16, max_length=16)
    active_at: datetime


__all__ = [
    "CursorPagePATSummary",
    "LoginRequest",
    "LoginResponse",
    "LogoutRequest",
    "MfaLoginChallenge",
    "PATMintRequest",
    "PATMinted",
    "PATSummary",
    "RefreshRequest",
    "SigningKeyChallengeResponse",
    "SigningKeyRegisterRequest",
    "SigningKeyRegisterResponse",
    "StreamTokenMinted",
    "StreamTokenRequest",
    "TokenPair",
    "UserMe",
]
