# SPDX-License-Identifier: AGPL-3.0-or-later
"""Forum collector 429 cooldown gate + evasion-level pacing (hostile-board tradecraft).

The ban-safety path: a 429 must put the collector FULLY SILENT for a jittered
Retry-After, and a request made DURING that window must not hit the wire at all
(poking a rate-limited board re-arms its timer — measured on pwnforums). The
evasion level is just a pacing preset expanded at provision time.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from eyenet.api.v1.identities.api_create_identity import _build_source_config
from eyenet.bus import MemoryBus
from eyenet.collectors.forum.real import (
    _DEFAULT_RETRY_AFTER,
    MyBBForumCollector,
    RateLimited,
    resolve_evasion_pacing,
)
from eyenet.contracts.enums import SourceKind
from eyenet.identity_pool import FileIdentityPool, IdentityFile, IdentityFileEntry
from eyenet.identity_pool.loader import dump
from eyenet.storage.factory import get_repository


def _pool(tmp_path: Path) -> FileIdentityPool:
    entry = IdentityFileEntry(
        name="pwn",
        source=SourceKind.FORUM,
        cooldown_seconds=0,
        forum_base_url="http://host.onion",
        forum_delay_min=0.0,
        forum_delay_max=0.0,
    )
    cfg = tmp_path / "identities.toml"
    dump(IdentityFile(identities=[entry]), cfg)
    return FileIdentityPool(cfg, check_session_files=False)


def _collector(tmp_path: Path, client: httpx.AsyncClient) -> MyBBForumCollector:
    coll = MyBBForumCollector(
        bus=MemoryBus(),
        storage=get_repository(in_memory=True),
        pool=_pool(tmp_path),
        identity_name="pwn",
        http_client=client,
    )
    coll._delay_min = coll._delay_max = 0.0  # no throttle sleep in tests
    return coll


# -- evasion-level resolution (pure) -----------------------------------------


@pytest.mark.unit
def test_resolve_evasion_pacing_names_aliases_and_misses() -> None:
    assert resolve_evasion_pacing("lurker") == (20.0, 60.0)
    assert resolve_evasion_pacing("E1") == (20.0, 60.0)  # nmap-style alias
    assert resolve_evasion_pacing(" LURKER ") == (20.0, 60.0)  # case/space-insensitive
    assert resolve_evasion_pacing(None) is None
    assert resolve_evasion_pacing("") is None
    assert resolve_evasion_pacing("turbo") is None  # unknown
    # monotone: ghost is slowest, smash fastest
    lo = resolve_evasion_pacing("ghost")
    hi = resolve_evasion_pacing("smash")
    assert lo is not None and hi is not None and lo[0] > hi[1]


@pytest.mark.unit
def test_build_source_config_expands_level_to_delays() -> None:
    cfg = _build_source_config(
        SourceKind.FORUM,
        telegram_api_id=None,
        telegram_api_hash=None,
        monitor_groups=None,
        forum_base_url="http://host.onion",
        forum_evasion_level="lurker",
    )
    assert cfg["forum_evasion_level"] == "lurker"
    assert (cfg["forum_delay_min"], cfg["forum_delay_max"]) == (20.0, 60.0)


@pytest.mark.unit
def test_build_source_config_rejects_unknown_level() -> None:
    from fastapi.exceptions import RequestValidationError

    with pytest.raises(RequestValidationError):
        _build_source_config(
            SourceKind.FORUM,
            telegram_api_id=None,
            telegram_api_hash=None,
            monitor_groups=None,
            forum_base_url="http://host.onion",
            forum_evasion_level="nope",
        )


# -- the 429 cooldown gate (the ban-safety path) ------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_429_arms_silent_cooldown_and_never_pokes(tmp_path: Path) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429, headers={"Retry-After": "600"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://host.onion"
    ) as client:
        coll = _collector(tmp_path, client)

        # First request trips the limiter → RateLimited, one wire hit.
        with pytest.raises(RateLimited):
            await coll._get("/Forum-Databases")
        assert calls["n"] == 1
        assert coll._cooldown_until > 0

        # A request during cooldown must NOT touch the wire (poking resets the timer).
        with pytest.raises(RateLimited):
            await coll._get("/Forum-Leaks")
        assert calls["n"] == 1  # still one — gated before the request


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cooldown_padded_past_retry_after_and_clears(tmp_path: Path) -> None:
    status = {"code": 429}

    def handler(request: httpx.Request) -> httpx.Response:
        if status["code"] == 429:
            return httpx.Response(429, headers={"Retry-After": "600"})
        return httpx.Response(200, text="ok")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://host.onion"
    ) as client:
        coll = _collector(tmp_path, client)
        import time

        before = time.monotonic()
        with pytest.raises(RateLimited):
            await coll._get("/x")
        # Silent window is Retry-After PLUS jitter — never the exact 600 (robotic tell).
        assert coll._cooldown_until - before > 600.0

        # Once the window lapses, the next request goes through normally.
        status["code"] = 200
        coll._cooldown_until = 0.0
        resp = await coll._get("/x")
        assert resp.status_code == 200


@pytest.mark.unit
@pytest.mark.asyncio
async def test_429_without_retry_after_uses_default(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429)  # no Retry-After header

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://host.onion"
    ) as client:
        coll = _collector(tmp_path, client)
        import time

        before = time.monotonic()
        with pytest.raises(RateLimited):
            await coll._get("/x")
        assert coll._cooldown_until - before >= _DEFAULT_RETRY_AFTER


@pytest.mark.unit
def test_identity_entry_round_trips_evasion_level(tmp_path: Path) -> None:
    entry = IdentityFileEntry(
        name="pwn",
        source=SourceKind.FORUM,
        forum_base_url="http://host.onion",
        forum_evasion_level="lurker",
    )
    out = tmp_path / "identities.toml"
    dump(IdentityFile(identities=[entry]), out)
    assert 'forum_evasion_level = "lurker"' in out.read_text(encoding="utf-8")
