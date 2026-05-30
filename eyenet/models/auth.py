"""Auth tables (M9.A1, API_PLAN §4.1-§4.6).

Four new tables that make A2's JWT login/refresh/logout/me handlers possible:

* :class:`SystemUserCredentialTable` — argon2id password hash + Fernet-encrypted
  MFA secret (see :mod:`eyenet.api.auth._mfa_key`), separated from the user
  profile so credentials and profile have different access patterns / audit
  scopes.
* :class:`RefreshTokenTable` — opaque-secret-hash chain with self-referential
  ``replaced_by`` FK for rotation tracking. CHECK constraint enforces
  replacement-implies-revocation; admin-revoked-but-not-replaced (logout) is
  legal so we use the implication, not the biconditional.
* :class:`JwtDenylistTable` — forced revocation of unexpired access tokens,
  keyed by ``jti``, indexed by ``expires_at`` for the future purge sweep.
* :class:`SystemUserScopeTable` — explicit per-user scope grants, additive
  to ``ROLE_BASELINE`` per §4.6. Composite PK ``(user_id, scope)``;
  revocation = DELETE.

``user_id`` FKs use the standard ``Field(foreign_key="system_user.id")`` —
ON DELETE CASCADE is not enforced at the SQLite layer (matches the rest of
the codebase). Application-level cleanup runs via ``delete_credential`` and
friends; cascade semantics land when a Postgres backend exists.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON, CheckConstraint, Column, Index
from sqlmodel import Field, SQLModel

from ._base import new_uuid7


class SystemUserCredentialTable(SQLModel, table=True):
    """`system_user_credential` — argon2id hash + MFA secret (M9.A1)."""

    __tablename__ = "system_user_credential"

    # user_id is BOTH the PK and the FK — one credential per user.
    user_id: UUID = Field(foreign_key="system_user.id", primary_key=True)
    password_hash: str = Field(max_length=256)
    password_updated_at: datetime
    mfa_secret_encrypted: str | None = Field(default=None, max_length=512)


class RefreshTokenTable(SQLModel, table=True):
    """`refresh_token` — opaque-secret hash chain (API_PLAN §4.2)."""

    __tablename__ = "refresh_token"
    __table_args__ = (
        # Replacement implies revocation — admin-revoked-without-replacement
        # (logout case) is legal, so use implication, not biconditional.
        CheckConstraint(
            "replaced_by IS NULL OR revoked_at IS NOT NULL",
            name="ck_refresh_token_replaced_implies_revoked",
        ),
        CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= issued_at",
            name="ck_refresh_token_revoked_after_issued",
        ),
        Index("ix_refresh_token_expires_at", "expires_at"),
    )

    token_id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    user_id: UUID = Field(foreign_key="system_user.id", index=True)
    # sha256 hex digest of the opaque 32-byte refresh secret. UNIQUE so the
    # lookup path is an index seek and double-mint is unrepresentable.
    hash: str = Field(unique=True, index=True, min_length=64, max_length=64)
    issued_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None
    replaced_by: UUID | None = Field(default=None, foreign_key="refresh_token.token_id")


class JwtDenylistTable(SQLModel, table=True):
    """`jwt_denylist` — forced revocation of unexpired access tokens (API_PLAN §4.2)."""

    __tablename__ = "jwt_denylist"
    __table_args__ = (Index("ix_jwt_denylist_expires_at", "expires_at"),)

    jti: UUID = Field(primary_key=True)
    user_id: UUID = Field(foreign_key="system_user.id", index=True)
    denied_at: datetime
    expires_at: datetime


class SystemUserScopeTable(SQLModel, table=True):
    """`system_user_scope` — explicit per-user scope grants (API_PLAN §4.6)."""

    __tablename__ = "system_user_scope"

    user_id: UUID = Field(foreign_key="system_user.id", primary_key=True)
    scope: str = Field(primary_key=True, max_length=64)
    granted_at: datetime
    granted_by_user_id: UUID = Field(foreign_key="system_user.id")


class PersonalAccessTokenTable(SQLModel, table=True):
    """`personal_access_token` — non-interactive bearer credential (API_PLAN §4.3, M9.A4).

    A PAT authenticates automation (Prometheus scraping, read-only feeds)
    without a human JWT session. ``hash`` is HMAC-SHA256(pepper, secret) —
    UNIQUE so the per-request auth lookup is an index seek. ``prefix`` is the
    plaintext 22-char display segment, also UNIQUE for a defense-in-depth
    match at verify time. ``scopes`` are frozen at mint (M9.A4 decision):
    the row carries exactly the scopes captured then, until ``revoked_at``.
    """

    __tablename__ = "personal_access_token"
    __table_args__ = (
        CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at",
            name="ck_personal_access_token_revoked_after_created",
        ),
        Index("ix_personal_access_token_user_created", "user_id", "created_at"),
    )

    token_id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    user_id: UUID = Field(foreign_key="system_user.id", index=True)
    name: str = Field(max_length=128)
    prefix: str = Field(unique=True, index=True, min_length=1, max_length=32)
    # HMAC-SHA256(pepper, secret) hex digest. UNIQUE → indexed equality
    # lookup on the per-request auth hot path. The pepper lives off-database
    # (<data_dir>/jwt/pat_pepper) so DB exfiltration alone yields nothing.
    hash: str = Field(unique=True, index=True, min_length=64, max_length=64)
    scopes: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    created_at: datetime
    last_used_at: datetime | None = None
    expires_at: datetime | None = None
    revoked_at: datetime | None = None


__all__ = [
    "JwtDenylistTable",
    "PersonalAccessTokenTable",
    "RefreshTokenTable",
    "SystemUserCredentialTable",
    "SystemUserScopeTable",
]
