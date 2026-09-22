# SPDX-License-Identifier: AGPL-3.0-or-later
"""Direct-call unit tests for the M9.F1 actor read handlers."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import uuid4

import pytest

from eyenet.api.deps import CurrentUser, ResourceNotFound
from eyenet.api.deps_paging import CursorParams
from eyenet.api.v1.actors.api_get_actor import actors_get
from eyenet.api.v1.actors.api_get_neighbors import actors_neighbors
from eyenet.api.v1.actors.api_get_timeline import actors_timeline
from eyenet.api.v1.actors.api_list_observations import actors_observations
from eyenet.contracts.enums import SourceKind, ValueKind
from eyenet.contracts.observation import ObservationRow
from eyenet.storage.repository import BaseRepository
from tests._seed import seed_telegram_fixture

pytestmark = pytest.mark.unit


def _page(limit: int = 50, *, offset: int = 0, total: bool = True) -> CursorParams:
    return CursorParams(offset=offset, limit=limit, include_total=total)


async def _seed_actor(storage: BaseRepository, now: datetime, *, handle: str | None = "alice"):
    source_id = await storage.upsert_source(
        kind=SourceKind.TELEGRAM, display_name="tg", created_at=now
    )
    return await storage.upsert_actor(
        source_id=source_id,
        actor_key="actor:u",
        platform_userid="42",
        handle=handle,
        display_name="Alice",
        seen_at=now,
    )


async def test_actors_get_detail(
    storage: BaseRepository, now: datetime, mkuser: Callable[..., CurrentUser]
) -> None:
    actor_id = await _seed_actor(storage, now)
    detail = await actors_get(actor_id, mkuser("read:actors"), storage)
    assert detail.actor_id == actor_id
    assert detail.primary_handle == "alice"
    assert detail.platforms == [SourceKind.TELEGRAM.value]
    assert detail.persona_id is None


async def test_actors_get_surfaces_aliases(
    storage: BaseRepository, now: datetime, mkuser: Callable[..., CurrentUser]
) -> None:
    from eyenet.contracts.enums import ActorAliasKind
    from eyenet.models.actor import ActorAliasHistoryTable

    actor_id = await _seed_actor(storage, now)
    async with storage.session() as session:
        session.add(
            ActorAliasHistoryTable(
                actor_id=actor_id, kind=ActorAliasKind.HANDLE, value="alice_old",
                observed_from=now - timedelta(days=3), observed_until=now,
            )
        )
        await session.commit()
    detail = await actors_get(actor_id, mkuser("read:actors"), storage)
    assert detail.alias_count == 1
    assert detail.aliases[0].value == "alice_old"
    assert detail.aliases[0].kind is ActorAliasKind.HANDLE


async def test_actors_get_handle_fallback(
    storage: BaseRepository, now: datetime, mkuser: Callable[..., CurrentUser]
) -> None:
    actor_id = await _seed_actor(storage, now, handle=None)
    detail = await actors_get(actor_id, mkuser("read:actors"), storage)
    assert detail.primary_handle == "42"


async def test_actors_get_unknown_raises(
    storage: BaseRepository, mkuser: Callable[..., CurrentUser]
) -> None:
    with pytest.raises(ResourceNotFound):
        await actors_get(uuid4(), mkuser("read:actors"), storage)


async def test_actors_neighbors_typed_and_skips_member_of(
    storage: BaseRepository, now: datetime, mkuser: Callable[..., CurrentUser]
) -> None:
    a = await _seed_actor(storage, now)
    b = uuid4()
    await storage.upsert_graph_edge(
        "linked_to",
        a,
        b,
        {"state": "confirmed", "method": "sty", "score": 0.9, "linkage_id": str(uuid4())},
    )
    await storage.upsert_graph_edge("belongs_to_persona", a, uuid4(), {"since": now.isoformat()})
    await storage.upsert_graph_edge("member_of", a, uuid4(), {})  # not part of the union
    result = await actors_neighbors(a, mkuser("read:actors"), storage, _page())
    kinds = {e.edge_type for e in result.items}
    assert kinds == {"linked_to", "belongs_to_persona"}  # member_of skipped
    assert result.estimated_total == 3  # count is over all outbound edges


async def test_actors_neighbors_unknown_raises(
    storage: BaseRepository, mkuser: Callable[..., CurrentUser]
) -> None:
    with pytest.raises(ResourceNotFound):
        await actors_neighbors(uuid4(), mkuser("read:actors"), storage, _page())


async def test_actors_observations_paginates(
    storage: BaseRepository, now: datetime, mkuser: Callable[..., CurrentUser]
) -> None:
    actor_id = await _seed_actor(storage, now)
    for i in range(3):
        await storage.put_observation(
            ObservationRow(
                actor_id=actor_id,
                primitive_namespace="lex",
                primitive_name="e",
                primitive_version="1",
                value_kind=ValueKind.NUMERIC,
                value_numeric=float(i),
                observed_at=now + timedelta(minutes=i),
                sensor_instance="s",
            )
        )
    page1 = await actors_observations(actor_id, mkuser("read:observations"), storage, _page(2))
    assert len(page1.items) == 2
    assert page1.estimated_total == 3
    assert page1.next_cursor is not None


async def test_actors_observations_unknown_raises(
    storage: BaseRepository, mkuser: Callable[..., CurrentUser]
) -> None:
    with pytest.raises(ResourceNotFound):
        await actors_observations(uuid4(), mkuser("read:observations"), storage, _page())


async def test_actors_timeline_merges(
    storage: BaseRepository, now: datetime, mkuser: Callable[..., CurrentUser]
) -> None:
    _, _, actor_ids = await seed_telegram_fixture(
        storage,
        [
            {
                "actor_key": "actor:tl",
                "platform_msgid": "1",
                "body": "hi",
                "sent_at_source": now.isoformat(),
            },
            {
                "actor_key": "actor:tl",
                "platform_msgid": "2",
                "body": "yo",
                "sent_at_source": (now + timedelta(minutes=5)).isoformat(),
            },
        ],
        now,
    )
    actor_id = actor_ids["actor:tl"]
    await storage.put_observation(
        ObservationRow(
            actor_id=actor_id,
            primitive_namespace="lex",
            primitive_name="x",
            primitive_version="1",
            value_kind=ValueKind.NUMERIC,
            observed_at=now + timedelta(minutes=2),
            sensor_instance="s",
        )
    )
    result = await actors_timeline(actor_id, mkuser("read:observations"), storage, _page())
    kinds = [e.kind for e in result.items]
    assert kinds.count("message") == 2
    assert kinds.count("observation") == 1
    assert result.estimated_total == 3
    ts = [e.ts for e in result.items]
    assert ts == sorted(ts, reverse=True)


async def test_actors_timeline_unknown_raises(
    storage: BaseRepository, mkuser: Callable[..., CurrentUser]
) -> None:
    with pytest.raises(ResourceNotFound):
        await actors_timeline(uuid4(), mkuser("read:observations"), storage, _page())
