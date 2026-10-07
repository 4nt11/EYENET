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
from eyenet.collectors.forum._timing_presets import (
    DEFAULT_RETRY_AFTER,
    resolve_evasion_profile,
)
from eyenet.collectors.forum.real import MyBBForumCollector, RateLimited
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
def test_resolve_evasion_profile_names_aliases_and_misses() -> None:
    assert resolve_evasion_profile("lurker") == (20.0, 60.0, 1)
    assert resolve_evasion_profile("E1") == (20.0, 60.0, 1)  # nmap-style alias
    assert resolve_evasion_profile(" LURKER ") == (20.0, 60.0, 1)  # case/space-insensitive
    assert resolve_evasion_profile(None) is None
    assert resolve_evasion_profile("") is None
    assert resolve_evasion_profile("turbo") is None  # unknown
    # monotone: ghost is slowest, smash fastest
    lo = resolve_evasion_profile("ghost")
    hi = resolve_evasion_profile("smash")
    assert lo is not None and hi is not None and lo.delay_min > hi.delay_max
    # ghost discovers index-only (the paranoid default); louder levels descend
    assert resolve_evasion_profile("ghost").discovery_depth == 0
    assert resolve_evasion_profile("smash").discovery_depth >= 1


@pytest.mark.unit
def test_build_source_config_expands_level_to_knobs() -> None:
    cfg = _build_source_config(
        SourceKind.FORUM,
        telegram_api_id=None,
        telegram_api_hash=None,
        monitor_groups=None,
        forum_base_url="http://host.onion",
        forum_evasion_level="ghost",
    )
    assert cfg["forum_evasion_level"] == "ghost"
    assert (cfg["forum_delay_min"], cfg["forum_delay_max"]) == (90.0, 240.0)
    # ghost = index-only discovery: no per-forum subforum walk on (re)subscribe.
    assert cfg["forum_discovery_depth"] == 0


@pytest.mark.unit
def test_build_source_config_carries_engine_and_rejects_unknown() -> None:
    cfg = _build_source_config(
        SourceKind.FORUM,
        telegram_api_id=None,
        telegram_api_hash=None,
        monitor_groups=None,
        forum_base_url="https://board.test",
        forum_engine="XenForo",
    )
    assert cfg["forum_engine"] == "xenforo"  # normalized lower

    from fastapi.exceptions import RequestValidationError

    with pytest.raises(RequestValidationError):
        _build_source_config(
            SourceKind.FORUM,
            telegram_api_id=None,
            telegram_api_hash=None,
            monitor_groups=None,
            forum_base_url="https://board.test",
            forum_engine="phpbb",
        )


@pytest.mark.unit
def test_identity_entry_round_trips_engine_and_steady_pages(tmp_path: Path) -> None:
    entry = IdentityFileEntry(
        name="df",
        source=SourceKind.FORUM,
        forum_base_url="https://board.test",
        forum_engine="xenforo",
        forum_steady_pages=5,
    )
    out = tmp_path / "identities.toml"
    dump(IdentityFile(identities=[entry]), out)
    text = out.read_text(encoding="utf-8")
    assert 'forum_engine = "xenforo"' in text
    assert "forum_steady_pages = 5" in text
    from eyenet.identity_pool.loader import load

    reloaded = load(out, check_session_files=False).identities[0]
    assert reloaded.forum_engine == "xenforo"
    assert reloaded.forum_steady_pages == 5


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
        assert coll._cooldown_until - before >= DEFAULT_RETRY_AFTER


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tick_is_silent_during_cooldown(tmp_path: Path) -> None:
    # During a 429 cooldown tick() must return BEFORE entering the sweep: no wire
    # hit, no sweep_start, no per-second busy-spin (which spammed the DB).
    import time
    from uuid import uuid4

    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, text="ok")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://host.onion"
    ) as client:
        coll = _collector(tmp_path, client)
        coll._source_uuid = uuid4()  # past the tick() None-guard
        coll._cooldown_until = time.monotonic() + 600  # mid-cooldown
        await coll.tick()
        assert calls["n"] == 0  # returned before any sweep/request


@pytest.mark.unit
def test_identity_detail_surfaces_running_profile() -> None:
    # The read surface must show which pacing profile a collector is running.
    from uuid import uuid4

    from eyenet.api.v1.schemas.identities import IdentityDetail
    from eyenet.contracts.identity import IdentityRow

    row = IdentityRow(
        name="pwn",
        source_id=uuid4(),
        session_path="/x",
        source_config={
            "forum_base_url": "http://host.onion",
            "forum_evasion_level": "lurker",
            "forum_delay_min": 20.0,
            "forum_delay_max": 60.0,
        },
    )
    detail = IdentityDetail.from_domain(row)
    assert detail.forum_evasion_level == "lurker"
    assert (detail.forum_delay_min, detail.forum_delay_max) == (20.0, 60.0)


@pytest.mark.unit
def test_identity_detail_profile_none_for_non_forum() -> None:
    from uuid import uuid4

    from eyenet.api.v1.schemas.identities import IdentityDetail
    from eyenet.contracts.identity import IdentityRow

    row = IdentityRow(name="tg", source_id=uuid4(), session_path="/x")
    detail = IdentityDetail.from_domain(row)
    assert detail.forum_evasion_level is None
    assert detail.forum_delay_min is None


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


@pytest.mark.unit
@pytest.mark.asyncio
async def test_request_hard_timeout_backstops_a_hung_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    """A board request that hangs past the hard deadline raises httpx.ReadTimeout (which
    the callers handle) instead of wedging the sweep — the pwnforums-over-Tor freeze."""
    import asyncio

    import eyenet.collectors.forum.real as fr

    monkeypatch.setattr(fr, "_REQUEST_HARD_TIMEOUT", 0.05)

    async def _hang() -> None:
        await asyncio.sleep(10)

    with pytest.raises(httpx.ReadTimeout):
        await fr.MyBBForumCollector._request(_hang(), "http://host.onion/slow")
