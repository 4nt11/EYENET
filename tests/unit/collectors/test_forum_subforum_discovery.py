# SPDX-License-Identifier: AGPL-3.0-or-later
"""Subforum discovery: enumerate descends the forum tree to forum_discovery_depth.

Crawling is NOT exercised here (that stays flat + operator-gated); this pins only
that nested subforums are SURFACED as monitorable FORUM_CATEGORY units.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from eyenet.bus import MemoryBus
from eyenet.collectors.forum.real import MyBBForumCollector
from eyenet.contracts.enums import SourceKind
from eyenet.identity_pool import FileIdentityPool, IdentityFile, IdentityFileEntry
from eyenet.identity_pool.loader import dump
from eyenet.storage.factory import get_repository


def _subforums(*slugs: str) -> str:
    rows = "".join(f"<tr><td class='trow1'><a href='{s}'>{s}</a></td></tr>" for s in slugs)
    return f"<table class='forum-display__subforums tborder'><tbody>{rows}</tbody></table>"


# Board tree:  index -> {Databases, Stealer-Logs}
#              Databases -> Removed-Content -> Removed-Deep
#              Stealer-Logs -> (none)
# Each category page also carries nav/breadcrumb Forum-* decoys that must be ignored.
_NAV = "<ul class='sidenav__menu nav'><a href='Forum-Databases'>nav</a></ul>"
_PAGES = {
    "/": "<a href='Forum-Databases'>DB</a><a href='Forum-Stealer-Logs'>SL</a>",
    "/Forum-Databases": _NAV + _subforums("Forum-Databases-Removed-Content"),
    "/Forum-Databases-Removed-Content": _NAV + _subforums("Forum-Databases-Removed-Deep"),
    "/Forum-Databases-Removed-Deep": "<p>leaf</p>",
    "/Forum-Stealer-Logs": "<p>leaf</p>",
}


def _client() -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=_PAGES.get(request.url.path, "<p>404</p>"))

    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://forum.test")


def _collector(tmp_path: Path, depth: int) -> MyBBForumCollector:
    entry = IdentityFileEntry(
        name="df",
        source=SourceKind.FORUM,
        cooldown_seconds=0,
        forum_base_url="https://forum.test",
        forum_delay_min=0.0,
        forum_delay_max=0.0,
    )
    cfg = tmp_path / "identities.toml"
    dump(IdentityFile(identities=[entry]), cfg)
    coll = MyBBForumCollector(
        bus=MemoryBus(),
        storage=get_repository(in_memory=True),
        pool=FileIdentityPool(cfg, check_session_files=False),
        identity_name="df",
        http_client=_client(),
    )
    coll._identity_name = "df"
    coll._delay_min = coll._delay_max = 0.0
    coll._discovery_depth = depth
    return coll


@pytest.mark.unit
@pytest.mark.asyncio
async def test_scan_persists_index_before_descending(tmp_path: Path) -> None:
    # The fix: scan_visible_groups must persist the index's top-level categories
    # BEFORE it fetches any subforum page — so top-level visibility appears after
    # the single index request, not after the whole (slow, paced) depth-N walk.
    from datetime import UTC, datetime

    coll = _collector(tmp_path, depth=1)
    events: list[tuple[str, str]] = []

    orig_get = coll._get

    async def rec_get(url: str, **kw: object) -> httpx.Response:
        events.append(("GET", url))
        return await orig_get(url, **kw)  # type: ignore[arg-type]

    coll._get = rec_get  # type: ignore[method-assign]
    storage = coll._storage
    orig_ensure = storage.ensure_candidate

    async def rec_ensure(**kw: object) -> object:
        events.append(("PERSIST", str(kw["platform_groupid"])))
        return await orig_ensure(**kw)  # type: ignore[arg-type]

    storage.ensure_candidate = rec_ensure  # type: ignore[method-assign]

    sid = await storage.upsert_source(
        kind=SourceKind.FORUM, display_name="df", created_at=datetime.now(tz=UTC)
    )
    n = await coll.scan_visible_groups(source_id=sid)

    assert n == 3  # Databases, Stealer-Logs (roots) + Databases-Removed-Content (depth 1)
    assert events[0] == ("GET", "/")  # the single index request comes first
    # Both top-level roots are persisted before the FIRST subforum-page fetch.
    first_subforum_get = next(i for i, e in enumerate(events) if e[0] == "GET" and e[1] != "/")
    roots = {("PERSIST", "Forum-Databases"), ("PERSIST", "Forum-Stealer-Logs")}
    root_persists = [i for i, e in enumerate(events) if e in roots]
    assert len(root_persists) == 2
    assert all(p < first_subforum_get for p in root_persists), events


@pytest.mark.unit
@pytest.mark.asyncio
async def test_depth_2_surfaces_full_tree(tmp_path: Path) -> None:
    groups = await _collector(tmp_path, depth=2).enumerate_visible_groups()
    slugs = {g.platform_groupid for g in groups}
    assert slugs == {
        "Forum-Databases",
        "Forum-Stealer-Logs",
        "Forum-Databases-Removed-Content",
        "Forum-Databases-Removed-Deep",
    }
    # decoy nav link never becomes a duplicate root, and titles are humanized
    removed = next(g for g in groups if g.platform_groupid == "Forum-Databases-Removed-Content")
    assert removed.title == "Databases Removed Content"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_depth_1_stops_one_level_down(tmp_path: Path) -> None:
    slugs = {g.platform_groupid for g in await _collector(tmp_path, 1).enumerate_visible_groups()}
    assert "Forum-Databases-Removed-Content" in slugs  # one level down: yes
    assert "Forum-Databases-Removed-Deep" not in slugs  # two levels down: no


@pytest.mark.unit
@pytest.mark.asyncio
async def test_depth_0_is_index_only(tmp_path: Path) -> None:
    slugs = {g.platform_groupid for g in await _collector(tmp_path, 0).enumerate_visible_groups()}
    assert slugs == {"Forum-Databases", "Forum-Stealer-Logs"}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cycle_guard_no_dupes(tmp_path: Path) -> None:
    # A subforum that links back up to its ancestor must not loop or duplicate.
    coll = _collector(tmp_path, depth=5)
    _PAGES["/Forum-Databases-Removed-Deep"] = _subforums("Forum-Databases")  # back-edge
    try:
        groups = await coll.enumerate_visible_groups()
    finally:
        _PAGES["/Forum-Databases-Removed-Deep"] = "<p>leaf</p>"
    slugs = [g.platform_groupid for g in groups]
    assert len(slugs) == len(set(slugs))  # no duplicate despite the back-edge
