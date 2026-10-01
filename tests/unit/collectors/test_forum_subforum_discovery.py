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
