# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for eyenet.api.auth._cache — TTL cache + invalidation."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from eyenet.api.auth._cache import AuthCache
from eyenet.contracts.enums import SystemUserRole
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

_NOW = datetime(2026, 5, 26, tzinfo=UTC)


async def _seed_user(storage: BaseRepository, *, role: SystemUserRole = SystemUserRole.VIEWER):
    user_id = uuid4()
    await storage.put_system_user(
        user_id=user_id,
        username=f"u-{user_id.hex[:8]}",
        display_name="U",
        role=role,
        created_at=_NOW,
    )
    return user_id


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


@pytest.mark.unit
async def test_load_returns_active_user(storage: BaseRepository) -> None:
    cache = AuthCache(ttl_seconds=30)
    uid = await _seed_user(storage, role=SystemUserRole.ADMIN)
    ctx = await cache.get_or_load(uid, storage, now=_NOW)
    assert ctx is not None
    assert ctx.user.id == uid
    assert "admin:users" in ctx.effective_scopes


@pytest.mark.unit
async def test_load_returns_none_for_unknown_user(storage: BaseRepository) -> None:
    cache = AuthCache(ttl_seconds=30)
    assert await cache.get_or_load(uuid4(), storage, now=_NOW) is None


@pytest.mark.unit
async def test_inactive_user_returns_none(storage: BaseRepository) -> None:
    cache = AuthCache(ttl_seconds=30)
    uid = await _seed_user(storage)
    await storage.put_system_user(
        user_id=uid,
        username="dormant",
        display_name="X",
        role=SystemUserRole.VIEWER,
        is_active=False,
        created_at=_NOW,
    )
    assert await cache.get_or_load(uid, storage, now=_NOW) is None


@pytest.mark.unit
async def test_cache_hits_skip_storage(storage: BaseRepository) -> None:
    cache = AuthCache(ttl_seconds=30)
    uid = await _seed_user(storage)
    first = await cache.get_or_load(uid, storage, now=_NOW)
    assert first is not None

    # Mutate storage out from under the cache; cached read should be stale.
    await storage.grant_scope(
        user_id=uid,
        scope="read:metrics",
        granted_at=_NOW,
        granted_by_user_id=uuid4(),
    )
    second = await cache.get_or_load(uid, storage, now=_NOW)
    assert second is first  # same object — cache hit


@pytest.mark.unit
async def test_invalidate_forces_reload(storage: BaseRepository) -> None:
    cache = AuthCache(ttl_seconds=30)
    uid = await _seed_user(storage)
    first = await cache.get_or_load(uid, storage, now=_NOW)
    assert first is not None
    assert "read:metrics" not in first.effective_scopes

    await storage.grant_scope(
        user_id=uid,
        scope="read:metrics",
        granted_at=_NOW,
        granted_by_user_id=uuid4(),
    )
    cache.invalidate(uid)
    refreshed = await cache.get_or_load(uid, storage, now=_NOW)
    assert refreshed is not None
    assert "read:metrics" in refreshed.effective_scopes


@pytest.mark.unit
async def test_ttl_zero_disables_cache(storage: BaseRepository) -> None:
    cache = AuthCache(ttl_seconds=0)
    uid = await _seed_user(storage)
    first = await cache.get_or_load(uid, storage, now=_NOW)
    assert first is not None
    await storage.grant_scope(
        user_id=uid,
        scope="read:metrics",
        granted_at=_NOW,
        granted_by_user_id=uuid4(),
    )
    second = await cache.get_or_load(uid, storage, now=_NOW)
    assert second is not None
    # ttl=0 means every call refetches.
    assert "read:metrics" in second.effective_scopes
    assert second is not first


@pytest.mark.unit
async def test_ttl_expiry_refetches(storage: BaseRepository) -> None:
    cache = AuthCache(ttl_seconds=1)
    uid = await _seed_user(storage)
    first = await cache.get_or_load(uid, storage, now=_NOW)
    assert first is not None
    await asyncio.sleep(1.1)
    await storage.grant_scope(
        user_id=uid,
        scope="read:metrics",
        granted_at=_NOW,
        granted_by_user_id=uuid4(),
    )
    second = await cache.get_or_load(uid, storage, now=_NOW)
    assert second is not None
    assert "read:metrics" in second.effective_scopes


@pytest.mark.unit
async def test_concurrent_misses_coalesce(storage: BaseRepository) -> None:
    """Two concurrent misses on the same user_id must collapse to one load."""
    cache = AuthCache(ttl_seconds=30)
    uid = await _seed_user(storage)
    load_count = 0
    original_loader = cache._load  # type: ignore[attr-defined]

    async def counting_loader(user_id, st, *, now):
        nonlocal load_count
        load_count += 1
        return await original_loader(user_id, st, now=now)

    cache._load = counting_loader  # type: ignore[assignment, method-assign]

    results = await asyncio.gather(
        cache.get_or_load(uid, storage, now=_NOW),
        cache.get_or_load(uid, storage, now=_NOW),
        cache.get_or_load(uid, storage, now=_NOW),
    )
    assert all(r is results[0] for r in results)
    assert load_count == 1


@pytest.mark.unit
def test_from_env_reads_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EYENET_AUTH_CACHE_TTL", "0")
    cache = AuthCache.from_env()
    assert cache.ttl_seconds == 0

    monkeypatch.setenv("EYENET_AUTH_CACHE_TTL", "60")
    cache = AuthCache.from_env()
    assert cache.ttl_seconds == 60

    monkeypatch.setenv("EYENET_AUTH_CACHE_TTL", "garbage")
    cache = AuthCache.from_env()
    assert cache.ttl_seconds == 30  # default
