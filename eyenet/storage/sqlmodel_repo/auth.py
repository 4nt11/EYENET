# SPDX-License-Identifier: AGPL-3.0-or-later
"""AuthMixin — credential, refresh-token, jwt_denylist, scope CRUD (M9.A1).

ANSI SQL only (CLAUDE.md §2.3 Rule 1) — no ``ON CONFLICT``, no triggers.
The hot-path lookups (``get_refresh_token_by_hash``, ``is_jwt_denylisted``,
``list_explicit_scopes``) are simple indexed SELECTs; the audit-emission
hooks land in A2 (handlers), not here.

Every method is ``async`` even when the underlying query is read-only — this
is the established repo convention (see :class:`ClearanceMixin`).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.sql import func, update
from sqlmodel import col, select

from eyenet.contracts.auth import (
    JwtDenylistRow,
    RefreshTokenRow,
    SystemUserCredentialRow,
    SystemUserScopeRow,
)
from eyenet.contracts.mfa import MfaChallengeRow
from eyenet.models.auth import (
    JwtDenylistTable,
    RefreshTokenTable,
    SystemUserCredentialTable,
    SystemUserScopeTable,
)
from eyenet.models.mfa import MfaChallengeTable

from ._helpers import safe_session


def _coerce_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _credential_row(table: SystemUserCredentialTable) -> SystemUserCredentialRow:
    data = table.model_dump()
    data["password_updated_at"] = _coerce_utc(data.get("password_updated_at"))
    return SystemUserCredentialRow.model_validate(data)


def _refresh_row(table: RefreshTokenTable) -> RefreshTokenRow:
    data = table.model_dump()
    for k in ("issued_at", "expires_at", "revoked_at"):
        data[k] = _coerce_utc(data.get(k))
    return RefreshTokenRow.model_validate(data)


def _denylist_row(table: JwtDenylistTable) -> JwtDenylistRow:
    data = table.model_dump()
    for k in ("denied_at", "expires_at"):
        data[k] = _coerce_utc(data.get(k))
    return JwtDenylistRow.model_validate(data)


def _scope_row(table: SystemUserScopeTable) -> SystemUserScopeRow:
    data = table.model_dump()
    data["granted_at"] = _coerce_utc(data.get("granted_at"))
    return SystemUserScopeRow.model_validate(data)


def _mfa_row(table: MfaChallengeTable) -> MfaChallengeRow:
    data = table.model_dump()
    for k in ("issued_at", "expires_at", "consumed_at"):
        data[k] = _coerce_utc(data.get(k))
    return MfaChallengeRow.model_validate(data)


class AuthMixin:
    """CRUD surface for credentials, refresh tokens, JWT denylist, and scopes."""

    # =================================================================
    # Credentials
    # =================================================================

    async def put_credential(
        self,
        *,
        user_id: UUID,
        password_hash: str,
        password_updated_at: datetime,
        mfa_secret_encrypted: str | None = None,
    ) -> SystemUserCredentialRow:
        """Upsert one credential row keyed by user_id.

        A1 stores opaque hash strings; argon2id format enforcement happens
        at the A2 service layer.
        """
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            existing = await session.get(SystemUserCredentialTable, user_id)
            if existing is None:
                row = SystemUserCredentialTable(
                    user_id=user_id,
                    password_hash=password_hash,
                    password_updated_at=password_updated_at,
                    mfa_secret_encrypted=mfa_secret_encrypted,
                )
                session.add(row)
                await session.commit()
                await session.refresh(row)
                return _credential_row(row)
            existing.password_hash = password_hash
            existing.password_updated_at = password_updated_at
            existing.mfa_secret_encrypted = mfa_secret_encrypted
            session.add(existing)
            await session.commit()
            await session.refresh(existing)
            return _credential_row(existing)

    async def get_credential(self, user_id: UUID) -> SystemUserCredentialRow | None:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            row = await session.get(SystemUserCredentialTable, user_id)
            return _credential_row(row) if row is not None else None

    async def delete_credential(self, user_id: UUID) -> None:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            row = await session.get(SystemUserCredentialTable, user_id)
            if row is None:
                raise ValueError(f"credential for user {user_id} not found")
            await session.delete(row)
            await session.commit()

    # =================================================================
    # Refresh tokens
    # =================================================================

    async def create_refresh_token(
        self,
        *,
        user_id: UUID,
        hash_value: str,
        issued_at: datetime,
        expires_at: datetime,
    ) -> RefreshTokenRow:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            row = RefreshTokenTable(
                user_id=user_id,
                hash=hash_value,
                issued_at=issued_at,
                expires_at=expires_at,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return _refresh_row(row)

    async def get_refresh_token(self, token_id: UUID) -> RefreshTokenRow | None:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            row = await session.get(RefreshTokenTable, token_id)
            return _refresh_row(row) if row is not None else None

    async def get_refresh_token_by_hash(
        self,
        hash_value: str,
    ) -> RefreshTokenRow | None:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            result = await session.exec(
                select(RefreshTokenTable).where(RefreshTokenTable.hash == hash_value),
            )
            row = result.one_or_none()
            return _refresh_row(row) if row is not None else None

    async def revoke_refresh_token(
        self,
        *,
        token_id: UUID,
        revoked_at: datetime,
        replaced_by: UUID | None = None,
    ) -> RefreshTokenRow:
        """Mark a refresh token revoked (and optionally chained to a replacement).

        Raises :class:`ValueError` if the token doesn't exist.
        """
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            row = await session.get(RefreshTokenTable, token_id)
            if row is None:
                raise ValueError(f"refresh_token {token_id} not found")
            row.revoked_at = revoked_at
            if replaced_by is not None:
                row.replaced_by = replaced_by
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return _refresh_row(row)

    # =================================================================
    # JWT denylist
    # =================================================================

    async def deny_jwt(
        self,
        *,
        jti: UUID,
        user_id: UUID,
        denied_at: datetime,
        expires_at: datetime,
    ) -> JwtDenylistRow:
        """Insert (or no-op return) a denylist entry. Idempotent on ``jti``."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            existing = await session.get(JwtDenylistTable, jti)
            if existing is not None:
                return _denylist_row(existing)
            row = JwtDenylistTable(
                jti=jti,
                user_id=user_id,
                denied_at=denied_at,
                expires_at=expires_at,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return _denylist_row(row)

    async def is_jwt_denylisted(self, jti: UUID) -> bool:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            row = await session.get(JwtDenylistTable, jti)
            return row is not None

    # =================================================================
    # Scope grants
    # =================================================================

    async def grant_scope(
        self,
        *,
        user_id: UUID,
        scope: str,
        granted_at: datetime,
        granted_by_user_id: UUID,
    ) -> SystemUserScopeRow:
        """Grant a scope to a user. Idempotent on ``(user_id, scope)`` — a
        re-grant returns the existing row without changing ``granted_at``.
        """
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            existing = await session.get(SystemUserScopeTable, (user_id, scope))
            if existing is not None:
                return _scope_row(existing)
            row = SystemUserScopeTable(
                user_id=user_id,
                scope=scope,
                granted_at=granted_at,
                granted_by_user_id=granted_by_user_id,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return _scope_row(row)

    async def revoke_scope(self, *, user_id: UUID, scope: str) -> None:
        """Revoke a per-user scope grant. Raises :class:`ValueError` if no row."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            row = await session.get(SystemUserScopeTable, (user_id, scope))
            if row is None:
                raise ValueError(f"scope grant ({user_id}, {scope!r}) not found")
            await session.delete(row)
            await session.commit()

    async def list_explicit_scopes(self, user_id: UUID) -> list[SystemUserScopeRow]:
        """Return all explicit scope grants for a user, ordered by granted_at."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = (
                select(SystemUserScopeTable)
                .where(SystemUserScopeTable.user_id == user_id)
                .order_by(col(SystemUserScopeTable.granted_at).asc())
            )
            result = await session.exec(stmt)
            return [_scope_row(r) for r in list(result)]

    # =================================================================
    # MFA challenges (M9.A3)
    # =================================================================

    async def create_mfa_challenge(
        self,
        *,
        user_id: UUID,
        issued_at: datetime,
        expires_at: datetime,
    ) -> MfaChallengeRow:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            row = MfaChallengeTable(
                user_id=user_id,
                issued_at=issued_at,
                expires_at=expires_at,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return _mfa_row(row)

    async def get_mfa_challenge(self, challenge_id: UUID) -> MfaChallengeRow | None:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            row = await session.get(MfaChallengeTable, challenge_id)
            return _mfa_row(row) if row is not None else None

    async def consume_mfa_challenge(
        self,
        *,
        challenge_id: UUID,
        consumed_at: datetime,
    ) -> MfaChallengeRow:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            row = await session.get(MfaChallengeTable, challenge_id)
            if row is None:
                raise ValueError(f"mfa_challenge {challenge_id} not found")
            if row.consumed_at is not None:
                raise ValueError(f"mfa_challenge {challenge_id} already consumed")
            row.consumed_at = consumed_at
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return _mfa_row(row)

    async def bump_mfa_challenge_failures(self, challenge_id: UUID) -> int:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            row = await session.get(MfaChallengeTable, challenge_id)
            if row is None:
                raise ValueError(f"mfa_challenge {challenge_id} not found")
            row.failed_attempts += 1
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return int(row.failed_attempts)

    async def count_recent_mfa_failures(
        self,
        *,
        user_id: UUID,
        since: datetime,
    ) -> int:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = select(func.count()).where(
                MfaChallengeTable.user_id == user_id,
                MfaChallengeTable.issued_at >= since,
                MfaChallengeTable.failed_attempts > 0,
            )
            result = await session.exec(stmt)
            total = result.one()
            return int(total)

    async def clear_mfa_failures(
        self,
        *,
        user_id: UUID,
        since: datetime,
    ) -> int:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = (
                update(MfaChallengeTable)
                .where(
                    MfaChallengeTable.user_id == user_id,  # type: ignore[arg-type]
                    MfaChallengeTable.issued_at >= since,  # type: ignore[arg-type]
                    MfaChallengeTable.failed_attempts > 0,  # type: ignore[arg-type]
                )
                .values(failed_attempts=0)
            )
            result = await session.exec(stmt)
            await session.commit()
            return int(result.rowcount or 0)


__all__ = ["AuthMixin"]
