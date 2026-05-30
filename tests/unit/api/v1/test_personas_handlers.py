# SPDX-License-Identifier: AGPL-3.0-or-later
"""Direct-call unit tests for the M9.F1 persona read handlers."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from uuid import uuid4

import pytest

from eyenet.api.deps import CurrentUser, ResourceNotFound
from eyenet.api.deps_paging import CursorParams
from eyenet.api.v1.personas.api_get_persona import personas_get
from eyenet.api.v1.personas.api_list_members import personas_members
from eyenet.contracts.enums import SourceKind
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit


def _page() -> CursorParams:
    return CursorParams(offset=0, limit=50, include_total=True)


async def _two_actor_persona(storage: BaseRepository, now: datetime):
    src = await storage.upsert_source(kind=SourceKind.TELEGRAM, display_name="tg", created_at=now)
    a = await storage.upsert_actor(
        source_id=src,
        actor_key="actor:a",
        platform_userid="1",
        handle="a",
        display_name="a",
        seen_at=now,
    )
    b = await storage.upsert_actor(
        source_id=src,
        actor_key="actor:b",
        platform_userid="2",
        handle="b",
        display_name="b",
        seen_at=now,
    )
    persona = await storage.merge_actors_into_persona(a, b, uuid4())
    return persona, a, b


async def test_personas_get(
    storage: BaseRepository, now: datetime, mkuser: Callable[..., CurrentUser]
) -> None:
    persona, _, _ = await _two_actor_persona(storage, now)
    detail = await personas_get(persona.id, mkuser("read:personas"), storage)
    assert detail.persona_id == persona.id
    assert detail.member_count == 2
    assert detail.label.startswith("persona-")


async def test_personas_get_unknown_raises(
    storage: BaseRepository, mkuser: Callable[..., CurrentUser]
) -> None:
    with pytest.raises(ResourceNotFound):
        await personas_get(uuid4(), mkuser("read:personas"), storage)


async def test_personas_members(
    storage: BaseRepository, now: datetime, mkuser: Callable[..., CurrentUser]
) -> None:
    persona, a, b = await _two_actor_persona(storage, now)
    page = await personas_members(persona.id, mkuser("read:personas"), storage, _page())
    assert page.estimated_total == 2
    assert {m.actor_id for m in page.items} == {a, b}


async def test_personas_members_unknown_raises(
    storage: BaseRepository, mkuser: Callable[..., CurrentUser]
) -> None:
    with pytest.raises(ResourceNotFound):
        await personas_members(uuid4(), mkuser("read:personas"), storage, _page())
