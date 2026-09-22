# SPDX-License-Identifier: AGPL-3.0-or-later
"""Direct-call unit test for GET /v1/actors (actors_list).

Bypasses ASGI routing (coverage can't trace it). Unfiltered browse surface:
all actors, newest-activity first, ActorSummary projection.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from eyenet.api.deps import CurrentUser
from eyenet.api.deps_paging import CursorParams
from eyenet.api.v1.actors.api_list_actors import actors_list
from eyenet.contracts.enums import SourceKind
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)


async def _seed_actor(storage: BaseRepository, key: str, handle: str | None) -> None:
    source_id = await storage.upsert_source(
        kind=SourceKind.TELEGRAM, display_name="telegram:test", created_at=_NOW
    )
    await storage.upsert_actor(
        source_id=source_id,
        actor_key=key,
        platform_userid=key[-8:],
        handle=handle,
        display_name=None,
        seen_at=_NOW,
    )


async def test_list_projects_summaries(
    storage: BaseRepository, mkuser: Callable[..., CurrentUser]
) -> None:
    await _seed_actor(storage, "tg:alpha", "alpha")
    page = CursorParams(offset=0, limit=50, include_total=True)
    res = await actors_list(mkuser(), storage, page)
    assert len(res.items) == 1
    assert res.estimated_total == 1
    assert res.items[0].primary_handle == "alpha"
    assert res.items[0].platforms == ["telegram"]


async def test_list_falls_back_to_platform_userid(
    storage: BaseRepository, mkuser: Callable[..., CurrentUser]
) -> None:
    await _seed_actor(storage, "tg:nohandle", None)
    page = CursorParams(offset=0, limit=50, include_total=False)
    res = await actors_list(mkuser(), storage, page)
    assert res.items[0].primary_handle == "nohandle"[-8:]
    assert res.estimated_total is None


async def test_list_empty(
    storage: BaseRepository, mkuser: Callable[..., CurrentUser]
) -> None:
    page = CursorParams(offset=0, limit=50, include_total=True)
    res = await actors_list(mkuser(), storage, page)
    assert res.items == []
    assert res.estimated_total == 0
