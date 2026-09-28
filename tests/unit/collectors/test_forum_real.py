# SPDX-License-Identifier: AGPL-3.0-or-later
"""`MyBBForumCollector` - fetch/parse/store/publish over a mocked transport."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from eyenet.bus import MemoryBus
from eyenet.collectors.forum.real import MyBBForumCollector
from eyenet.contracts.actor import actor_key
from eyenet.contracts.enums import SourceKind
from eyenet.contracts.raw_message import RawMessageEnvelope
from eyenet.identity_pool import FileIdentityPool, IdentityFile, IdentityFileEntry
from eyenet.identity_pool.loader import dump
from eyenet.service import run_service
from eyenet.storage.factory import get_repository

_FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "mybb_thread.html"
_THREAD_URL = "Thread-demo-leak--42"
_LOGGED_IN_INDEX = "<html><body><a href='member.php?action=logout'>Log Out</a></body></html>"
_GUEST_INDEX = "<html><body><form action='member.php?action=do_login'>Login</form></body></html>"


def _pool(tmp_path: Path, name: str) -> FileIdentityPool:
    entry = IdentityFileEntry(
        name=name,
        source=SourceKind.FORUM,
        cooldown_seconds=0,
        forum_base_url="https://forum.test",
        forum_thread_urls=[_THREAD_URL],
        forum_delay_min=0.0,  # no throttle sleep in tests
        forum_delay_max=0.0,
    )
    cfg = tmp_path / "identities.toml"
    dump(IdentityFile(identities=[entry]), cfg)
    return FileIdentityPool(cfg, check_session_files=False)


def _client(index_html: str) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/":
            return httpx.Response(200, text=index_html)
        if "Thread-" in path:
            return httpx.Response(200, text=_FIXTURE.read_text(encoding="utf-8"))
        return httpx.Response(404)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://forum.test")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ingests_and_publishes(tmp_path: Path) -> None:
    pool = _pool(tmp_path, "alpha_forum")
    bus = MemoryBus()
    storage = get_repository(data_dir=tmp_path / "data")

    captured: list[bytes] = []

    async def _recorder(_s: str, payload: bytes, _h: dict[str, str]) -> None:
        captured.append(payload)

    await bus.subscribe("raw.message.>", _recorder)

    async with _client(_LOGGED_IN_INDEX) as client:
        coll = MyBBForumCollector(
            bus=bus,
            storage=storage,
            pool=pool,
            identity_name="alpha_forum",
            http_client=client,
        )
        task = asyncio.create_task(run_service(coll, tick_interval=0.02))
        await asyncio.sleep(0.2)
        await coll.shutdown()
        await task

    # 2 posts in the fixture -> 2 envelopes, published ONCE despite re-polls
    # (put_message is idempotent on evidence_ref).
    assert len(captured) == 2
    envs = [RawMessageEnvelope.model_validate_json(p) for p in captured]
    assert {e.platform_msgid for e in envs} == {"1001", "1002"}
    for env in envs:
        assert env.source == SourceKind.FORUM
        assert env.platform_groupid == "42"  # tid parsed from Thread-...--42
        assert env.evidence_ref.startswith("forum:forum.test:42:")
    assert envs[0].actor_key in {
        actor_key(SourceKind.FORUM, "forum.test|alice"),
        actor_key(SourceKind.FORUM, "forum.test|bob_99"),
    }

    await storage.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_canary_detects_dead_session(tmp_path: Path) -> None:
    pool = _pool(tmp_path, "beta_forum")
    storage = get_repository(in_memory=True)

    async with _client(_GUEST_INDEX) as guest:
        dead = MyBBForumCollector(
            bus=MemoryBus(),
            storage=storage,
            pool=pool,
            identity_name="beta_forum",
            http_client=guest,
        )
        assert await dead._check_session() is False  # guest index: no logout marker

    async with _client(_LOGGED_IN_INDEX) as live:
        alive = MyBBForumCollector(
            bus=MemoryBus(),
            storage=storage,
            pool=pool,
            identity_name="beta_forum",
            http_client=live,
        )
        assert await alive._check_session() is True

    await storage.close()
