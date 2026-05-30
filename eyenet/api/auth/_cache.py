# SPDX-License-Identifier: AGPL-3.0-or-later
"""Per-process TTL cache for the (non-revocation) parts of CurrentUser.

API_PLAN §4.6 / §4.8 — every request needs user row + explicit scope
grants + active clearance grants. Three of those four lookups (the
fourth being the denylist) are stable across a token's 15-minute
lifetime in the common case, so we memoize. The denylist check is
ALWAYS uncached — revocation must propagate instantly.

Multi-worker note (CLAUDE.md §1 — small-operator scope): one uvicorn
worker per box is the design point, so process-local caching is
sufficient. When we add multi-worker, invalidation moves to a pub/sub
channel — this class is the swap point.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime
from typing import TYPE_CHECKING, NamedTuple
from uuid import UUID

from cachetools import TTLCache

from eyenet.api.auth._permissions import resolve_effective_scopes
from eyenet.contracts.system_user import SystemUserRow

if TYPE_CHECKING:
    from eyenet.storage.repository import BaseRepository

_DEFAULT_TTL_SECONDS = 30
_DEFAULT_MAX_ENTRIES = 1024


class AuthContext(NamedTuple):
    user: SystemUserRow
    effective_scopes: frozenset[str]
    loaded_at: datetime


class AuthCache:
    """TTL cache + per-user asyncio lock to coalesce concurrent misses."""

    def __init__(
        self,
        ttl_seconds: int = _DEFAULT_TTL_SECONDS,
        max_entries: int = _DEFAULT_MAX_ENTRIES,
    ) -> None:
        self._ttl = ttl_seconds
        self._cache: TTLCache[UUID, AuthContext] = TTLCache(
            maxsize=max_entries,
            ttl=max(ttl_seconds, 1),
        )
        self._locks: dict[UUID, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()

    @classmethod
    def from_env(cls) -> AuthCache:
        raw = os.environ.get("EYENET_AUTH_CACHE_TTL")
        if raw is None:
            return cls()
        try:
            ttl = int(raw)
        except ValueError:
            return cls()
        return cls(ttl_seconds=max(ttl, 0))

    @property
    def ttl_seconds(self) -> int:
        return self._ttl

    def _lock_for(self, user_id: UUID) -> asyncio.Lock:
        lock = self._locks.get(user_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[user_id] = lock
        return lock

    async def get_or_load(
        self,
        user_id: UUID,
        storage: BaseRepository,
        *,
        now: datetime,
    ) -> AuthContext | None:
        """Return cached context or load it from storage. ``None`` if the
        user doesn't exist or is inactive."""
        if self._ttl <= 0:
            return await self._load(user_id, storage, now=now)

        hit = self._cache.get(user_id)
        if hit is not None:
            return hit

        async with self._global_lock:
            lock = self._lock_for(user_id)

        async with lock:
            hit = self._cache.get(user_id)
            if hit is not None:
                return hit
            loaded = await self._load(user_id, storage, now=now)
            if loaded is not None:
                self._cache[user_id] = loaded
            return loaded

    @staticmethod
    async def _load(
        user_id: UUID,
        storage: BaseRepository,
        *,
        now: datetime,
    ) -> AuthContext | None:
        user = await storage.get_system_user_by_id(user_id)
        if user is None or not user.is_active:
            return None
        explicit = await storage.list_explicit_scopes(user_id)
        clearance = await storage.active_clearance_grants_for(user_id, now=now)
        scopes = resolve_effective_scopes(user, explicit, clearance)
        return AuthContext(user=user, effective_scopes=scopes, loaded_at=now)

    def invalidate(self, user_id: UUID) -> None:
        self._cache.pop(user_id, None)

    def clear(self) -> None:
        self._cache.clear()
        self._locks.clear()


__all__ = ["AuthCache", "AuthContext"]
