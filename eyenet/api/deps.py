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

import hmac
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
    hash_pat,
    is_pat,
    parse_pat,
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


class ResourceNotFound(Exception):  # noqa: N818 — domain term, not the generic ``*Error`` suffix
    """404-class failure: the addressed resource is absent OR the caller may
    not see it. The public ``detail`` is generic so a non-owner can't use the
    status code to enumerate other operators' resources. ``resource`` is for
    audit/logging only."""

    def __init__(self, resource: str) -> None:
        super().__init__(resource)
        self.resource = resource


@dataclass(frozen=True)
class CurrentUser:
    """Per-request identity + resolved authority.

    Two principal kinds resolve into this one shape:

    * **JWT** — ``jti`` set, ``pat_id`` None, ``effective_scopes`` resolved
      live from storage per request (identity-in-JWT / authority-in-storage).
    * **PAT** — ``pat_id`` set, ``jti`` None, ``effective_scopes`` frozen to
      the scopes captured at mint (M9.A4 decision); ``token_expires_at`` is
      the PAT's optional expiry (None = non-expiring).

    Handlers needing the interactive-session ``jti`` (logout) must guard on
    ``jti is None`` and reject PAT principals.
    """

    user_id: UUID
    username: str
    role: SystemUserRole
    effective_scopes: frozenset[str]
    token_expires_at: datetime | None
    jti: UUID | None = None
    pat_id: UUID | None = None


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


def get_pat_pepper(request: Request) -> bytes:
    pepper = getattr(request.app.state, "pat_pepper", None)
    if pepper is None:
        raise RuntimeError("app.state.pat_pepper is not configured")
    return cast("bytes", pepper)


def bearer_token(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> str:
    if authorization is None or not authorization.startswith(_BEARER_PREFIX):
        raise AuthError("missing_bearer")
    token = authorization[len(_BEARER_PREFIX) :].strip()
    if not token:
        raise AuthError("missing_bearer")
    return token


async def _resolve_pat(
    token: str,
    storage: BaseRepository,
    cache: AuthCache,
    pepper: bytes,
) -> CurrentUser:
    """Resolve a PAT bearer into the shared :class:`CurrentUser` principal.

    Every failure mode raises the flat ``AuthError`` (401, no oracle); the
    reason is recorded for audit only. Scopes are FROZEN to the values
    captured at mint (M9.A4 decision) — revocation, not live re-resolution,
    is the guard.
    """
    parsed = parse_pat(token)
    if parsed is None:
        raise AuthError("malformed_pat")
    prefix, secret = parsed
    row = await storage.get_personal_access_token_by_hash(hash_pat(pepper, secret))
    if row is None:
        raise AuthError("invalid_pat")
    # Defense-in-depth: the hash already uniquely identifies the row, but a
    # constant-time prefix compare rejects any logic error pairing a matching
    # digest with a mismatched display prefix.
    if not hmac.compare_digest(row.prefix, prefix):
        raise AuthError("pat_prefix_mismatch")
    now = datetime.now(tz=UTC)
    if row.revoked_at is not None:
        raise AuthError("pat_revoked")
    if row.expires_at is not None and row.expires_at <= now:
        raise AuthError("pat_expired")
    ctx = await cache.get_or_load(row.user_id, storage, now=now)
    if ctx is None:
        raise AuthError("user_not_found_or_inactive")
    await storage.touch_pat_last_used(token_id=row.token_id, now=now)
    return CurrentUser(
        user_id=ctx.user.id,
        username=ctx.user.username,
        role=ctx.user.role,
        effective_scopes=frozenset(row.scopes),
        token_expires_at=row.expires_at,
        jti=None,
        pat_id=row.token_id,
    )


async def get_current_user(
    token: Annotated[str, Depends(bearer_token)],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    cache: Annotated[AuthCache, Depends(get_auth_cache)],
    verifying_keys: Annotated[dict[str, VerifyingKey], Depends(get_verifying_keys)],
    pepper: Annotated[bytes, Depends(get_pat_pepper)],
) -> CurrentUser:
    # PAT bearers carry a fixed literal prefix — triage cheaply before the
    # JWT decode path. Both kinds resolve to the same CurrentUser shape.
    if is_pat(token):
        return await _resolve_pat(token, storage, cache, pepper)

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
        token_expires_at=claims.expires_at,
        jti=claims.jti,
        pat_id=None,
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
    "ResourceNotFound",
    "ScopeForbidden",
    "bearer_token",
    "get_audit",
    "get_auth_cache",
    "get_current_user",
    "get_mfa_key",
    "get_pat_pepper",
    "get_storage",
    "get_verifying_keys",
]
