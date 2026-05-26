"""Auth row contracts (M9.A1, API_PLAN §4.1-§4.6).

Plain :class:`BaseModel` rows — natural keys throughout (``user_id`` PK on
credential, composite PK on scope grants, ``jti`` PK on denylist, UUID7
``token_id`` PK on refresh tokens). No synthetic ``id`` column, so we
don't extend :class:`DbRowBase`.

Surface: db (Surface=db per PLAN §4.2 — no bus subject).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SystemUserCredentialRow(BaseModel):
    """One credential row per :class:`SystemUserRow` (one-to-one)."""

    model_config = ConfigDict(extra="forbid")

    user_id: UUID
    password_hash: str = Field(
        min_length=1,
        max_length=256,
        description="argon2id encoded hash; opaque to storage, format enforced by A2",
    )
    password_updated_at: datetime
    mfa_secret_encrypted: str | None = Field(
        default=None,
        max_length=512,
        description="Fernet-encrypted TOTP secret (see eyenet.api.auth._mfa_key); "
        "None if MFA not enrolled",
    )


class RefreshTokenRow(BaseModel):
    """Hashed refresh token with rotation chain (API_PLAN §4.2)."""

    model_config = ConfigDict(extra="forbid")

    token_id: UUID
    user_id: UUID
    hash: str = Field(
        min_length=64,
        max_length=64,
        description="sha256 hex digest of the opaque refresh secret",
    )
    issued_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None
    replaced_by: UUID | None = Field(
        default=None,
        description="Next token in the rotation chain; populated when this token "
        "was used in a /refresh and replaced. CHECK: replaced_by implies revoked.",
    )


class JwtDenylistRow(BaseModel):
    """Forced revocation of unexpired access tokens (API_PLAN §4.2 logout).

    Row is purgeable after ``expires_at`` (the original JWT ``exp``) — at that
    point the JWT is intrinsically invalid and the denylist entry is redundant.
    """

    model_config = ConfigDict(extra="forbid")

    jti: UUID
    user_id: UUID
    denied_at: datetime
    expires_at: datetime


class SystemUserScopeRow(BaseModel):
    """Explicit per-user scope grant, additive to ``ROLE_BASELINE`` (API_PLAN §4.6).

    Composite identity ``(user_id, scope)`` — revocation is row deletion. The
    grant/revoke audit trail lives in the audit_log chain emitted by A2's
    handlers, not in this table.
    """

    model_config = ConfigDict(extra="forbid")

    user_id: UUID
    scope: str = Field(min_length=1, max_length=64)
    granted_at: datetime
    granted_by_user_id: UUID


__all__ = [
    "JwtDenylistRow",
    "RefreshTokenRow",
    "SystemUserCredentialRow",
    "SystemUserScopeRow",
]
