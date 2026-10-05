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


_AUTHORLESS_THREAD = (
    "<html><body>"
    "<div class='post' id='post_9001'>"
    "<span class='post_date'>01-02-26, 09:30 AM</span>"
    "<div class='post_body'>orphan dump, no author anchor</div>"
    "</div></body></html>"
)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_blank_author_post_is_refused(tmp_path: Path) -> None:
    # A post whose author selector MISSES (no profile anchor) must NOT be ingested
    # as a phantom "<board>|" actor — the row is refused and nothing publishes.
    # Guards feedback_forum_theme_variants_break_selectors: a blank author is a
    # parse failure, not valid data.
    pool = _pool(tmp_path, "blank_forum")
    bus = MemoryBus()
    storage = get_repository(data_dir=tmp_path / "data")
    captured: list[bytes] = []

    async def _recorder(_s: str, payload: bytes, _h: dict[str, str]) -> None:
        captured.append(payload)

    await bus.subscribe("raw.message.>", _recorder)

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/":
            return httpx.Response(200, text=_LOGGED_IN_INDEX)
        if "Thread-" in path:
            return httpx.Response(200, text=_AUTHORLESS_THREAD)
        return httpx.Response(404)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://forum.test"
    ) as client:
        coll = MyBBForumCollector(
            bus=bus, storage=storage, pool=pool, identity_name="blank_forum", http_client=client
        )
        task = asyncio.create_task(run_service(coll, tick_interval=0.02))
        await asyncio.sleep(0.2)
        await coll.shutdown()
        await task

    # Blank-author row refused: nothing published, no phantom actor minted.
    assert captured == []
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


@pytest.mark.unit
@pytest.mark.asyncio
async def test_build_forum_client_selects_tls_impersonation(tmp_path: Path) -> None:
    # forum_tls_impersonate on a CLEARNET https board -> curl-cffi (real-Firefox
    # TLS); onion/Tor (proxy) -> httpx, even if impersonate is set (moot under Tor).
    ck = tmp_path / "cookies.txt"
    ck.write_text("raidforums.im\tFALSE\t/\tFALSE\t9999999999\tRF_sid\tabc\n", encoding="utf-8")
    pool = _pool(tmp_path, "rf")
    storage = get_repository(in_memory=True)
    coll = MyBBForumCollector(
        bus=MemoryBus(), storage=storage, pool=pool, identity_name="rf", session_key=None
    )

    clearnet = IdentityFileEntry(
        name="rf",
        source=SourceKind.FORUM,
        session_path=str(ck),
        forum_base_url="https://raidforums.im/",
        forum_tls_impersonate="firefox147",
    )
    c1 = await coll._build_forum_client(clearnet)
    assert type(c1).__name__ == "AsyncSession"  # curl-cffi, not httpx
    await (getattr(c1, "aclose", None) or c1.close)()

    onion = IdentityFileEntry(
        name="rf",
        source=SourceKind.FORUM,
        session_path=str(ck),
        forum_base_url="http://x.onion/",
        proxy_uri="socks5h://tor:9050",
        forum_tls_impersonate="firefox147",  # ignored on the Tor path
    )
    c2 = await coll._build_forum_client(onion)
    assert isinstance(c2, httpx.AsyncClient)
    await c2.aclose()

    bad = IdentityFileEntry(
        name="rf",
        source=SourceKind.FORUM,
        session_path=str(ck),
        forum_base_url="https://raidforums.im/",
        forum_tls_impersonate="chrome999",  # not an allowed target
    )
    with pytest.raises(RuntimeError, match="not an allowed Firefox target"):
        await coll._build_forum_client(bad)

    await storage.close()
