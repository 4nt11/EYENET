# SPDX-License-Identifier: AGPL-3.0-or-later
"""FastAPI dependencies — storage, audit, current_user, RequireScope.

API_PLAN §4.2 — identity-only JWT, authority resolved at request time.
``get_current_user`` does the per-request resolve; the result is cached
by :class:`AuthCache` between TTL ticks. ``is_jwt_denylisted`` is ALWAYS
re-checked uncached so revocation is instant.

The public 401/403 surface is ``AuthError`` / ``ScopeForbidden``; the
JWT/cache layers raise typed internal errors that this module catches
and re-raises as those.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, Final, cast
from uuid import UUID

from fastapi import Depends, Header, Request

from eyenet.api.auth import (
    AuthCache,
    JwtError,
    VerifyingKey,
    decode_access_token,
)

if TYPE_CHECKING:
    from cryptography.fernet import Fernet
from eyenet.contracts.enums import SystemUserRole
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

_BEARER_PREFIX: Final[str] = "Bearer "


class AuthError(Exception):
    """401-class failure. The ``reason`` is for audit only; the public
    ``detail`` is always ``"authentication failed"`` to avoid oracles."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ScopeForbidden(Exception):  # noqa: N818 — domain term, not the generic ``*Error`` suffix
    """403-class failure: caller is authenticated but lacks the required scope."""

    def __init__(self, scope: str) -> None:
        super().__init__(scope)
        self.scope = scope


@dataclass(frozen=True)
class CurrentUser:
    """Per-request identity + freshly-resolved authority."""

    user_id: UUID
    username: str
    role: SystemUserRole
    effective_scopes: frozenset[str]
    jti: UUID
    token_expires_at: datetime


def get_storage(request: Request) -> BaseRepository:
    storage = getattr(request.app.state, "storage", None)
    if storage is None:
        raise RuntimeError("app.state.storage is not configured")
    return cast("BaseRepository", storage)


def get_audit(request: Request) -> AuditEmitter:
    audit = getattr(request.app.state, "audit", None)
    if audit is None:
        raise RuntimeError("app.state.audit is not configured")
    return cast("AuditEmitter", audit)


def get_auth_cache(request: Request) -> AuthCache:
    cache = getattr(request.app.state, "auth_cache", None)
    if cache is None:
        raise RuntimeError("app.state.auth_cache is not configured")
    return cast("AuthCache", cache)


def get_mfa_key(request: Request) -> Fernet:
    fernet = getattr(request.app.state, "mfa_key", None)
    if fernet is None:
        raise RuntimeError("app.state.mfa_key is not configured")
    from cryptography.fernet import Fernet as _Fernet  # noqa: PLC0415

    return cast("_Fernet", fernet)


def get_verifying_keys(request: Request) -> dict[str, VerifyingKey]:
    keys = getattr(request.app.state, "verifying_keys", None)
    if keys is None:
        raise RuntimeError("app.state.verifying_keys is not configured")
    return cast("dict[str, VerifyingKey]", keys)


def bearer_token(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> str:
    if authorization is None or not authorization.startswith(_BEARER_PREFIX):
        raise AuthError("missing_bearer")
    token = authorization[len(_BEARER_PREFIX) :].strip()
    if not token:
        raise AuthError("missing_bearer")
    return token


async def get_current_user(
    token: Annotated[str, Depends(bearer_token)],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    cache: Annotated[AuthCache, Depends(get_auth_cache)],
    verifying_keys: Annotated[dict[str, VerifyingKey], Depends(get_verifying_keys)],
) -> CurrentUser:
    try:
        claims = decode_access_token(token, verifying_keys=verifying_keys)
    except JwtError as exc:
        raise AuthError(exc.args[0] if exc.args else "invalid_token") from exc

    if await storage.is_jwt_denylisted(claims.jti):
        raise AuthError("denylisted")

    now = datetime.now(tz=UTC)
    ctx = await cache.get_or_load(claims.user_id, storage, now=now)
    if ctx is None:
        raise AuthError("user_not_found_or_inactive")

    return CurrentUser(
        user_id=ctx.user.id,
        username=ctx.user.username,
        role=ctx.user.role,
        effective_scopes=ctx.effective_scopes,
        jti=claims.jti,
        token_expires_at=claims.expires_at,
    )


def RequireScope(  # noqa: N802 — FastAPI dependency factory convention
    scope: str,
) -> Callable[[CurrentUser], Awaitable[CurrentUser]]:
    """Dependency factory: 403 if the caller's effective scopes lack ``scope``."""

    async def _dep(
        current_user: Annotated[CurrentUser, Depends(get_current_user)],
    ) -> CurrentUser:
        if scope not in current_user.effective_scopes:
            raise ScopeForbidden(scope)
        return current_user

    _dep.__name__ = f"require_scope_{scope.replace(':', '_')}"
    return _dep


__all__ = [
    "AuthError",
    "CurrentUser",
    "RequireScope",
    "ScopeForbidden",
    "bearer_token",
    "get_audit",
    "get_auth_cache",
    "get_current_user",
    "get_mfa_key",
    "get_storage",
    "get_verifying_keys",
]
