# SPDX-License-Identifier: AGPL-3.0-or-later
"""Direct-call unit tests for the M9.F3 graph read handlers."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from uuid import uuid4

import pytest

from eyenet.api.deps import CurrentUser
from eyenet.api.deps_paging import CursorParams
from eyenet.api.v1.graph.api_get_stats import graph_stats
from eyenet.api.v1.graph.api_search import graph_search
from eyenet.contracts.enums import LinkageState, SourceKind
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit


def _page() -> CursorParams:
    return CursorParams(offset=0, limit=50, include_total=True)


async def _actor(storage: BaseRepository, now: datetime, key: str, handle: str):
    src = await storage.upsert_source(kind=SourceKind.TELEGRAM, display_name="tg", created_at=now)
    return await storage.upsert_actor(
        source_id=src,
        actor_key=key,
        platform_userid=key[-2:],
        handle=handle,
        display_name=handle.title(),
        seen_at=now,
    )


async def test_graph_stats_counts(
    storage: BaseRepository, now: datetime, mkuser: Callable[..., CurrentUser]
) -> None:
    await _actor(storage, now, "actor:1", "a")
    await _actor(storage, now, "actor:2", "b")
    await storage.insert_proposed_linkage(uuid4(), uuid4(), "m", 0.5, {})
    conf = await storage.insert_proposed_linkage(uuid4(), uuid4(), "n", 0.9, {})
    await storage.transition_linkage(conf.id, LinkageState.CONFIRMED, "x")
    stats = await graph_stats(mkuser("read:graph"), storage)
    assert stats.actors == 2
    assert stats.linkages.proposed == 1
    assert stats.linkages.confirmed == 1


async def test_graph_search_matches_with_platform(
    storage: BaseRepository, now: datetime, mkuser: Callable[..., CurrentUser]
) -> None:
    target = await _actor(storage, now, "actor:s1", "AliceCooper")
    await _actor(storage, now, "actor:s2", "bob")
    page = await graph_search(mkuser("read:graph"), storage, _page(), "alice")
    assert page.estimated_total == 1
    assert page.items[0].actor_id == target
    assert page.items[0].platforms == [SourceKind.TELEGRAM.value]


async def test_graph_search_no_match(
    storage: BaseRepository, now: datetime, mkuser: Callable[..., CurrentUser]
) -> None:
    await _actor(storage, now, "actor:s1", "alice")
    page = await graph_search(mkuser("read:graph"), storage, _page(), "zzznope")
    assert page.items == []
    assert page.next_cursor is None
