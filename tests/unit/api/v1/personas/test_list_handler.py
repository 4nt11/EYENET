# SPDX-License-Identifier: AGPL-3.0-or-later
"""Direct-call unit test for GET /v1/personas (personas_list).

Bypasses ASGI routing (coverage can't trace it). Newest-first browse surface;
member_count is len(member_actor_ids) off the row.
"""

from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

import pytest

from eyenet.api.deps import CurrentUser
from eyenet.api.deps_paging import CursorParams
from eyenet.api.v1.personas.api_list_personas import personas_list
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit


async def _seed_persona(storage: BaseRepository) -> None:
    # merge_actors_into_persona creates a persona with the two actors as members.
    await storage.merge_actors_into_persona(uuid4(), uuid4())


async def test_list_projects_summaries(
    storage: BaseRepository, mkuser: Callable[..., CurrentUser]
) -> None:
    await _seed_persona(storage)
    page = CursorParams(offset=0, limit=50, include_total=True)
    res = await personas_list(mkuser(), storage, page)
    assert len(res.items) == 1
    assert res.estimated_total == 1
    assert res.items[0].member_count == 2
    assert res.items[0].label  # synthesized non-null label


async def test_list_empty(
    storage: BaseRepository, mkuser: Callable[..., CurrentUser]
) -> None:
    page = CursorParams(offset=0, limit=50, include_total=True)
    res = await personas_list(mkuser(), storage, page)
    assert res.items == []
    assert res.estimated_total == 0
