# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/actors/{id}/timeline — the `kind` stream filter."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

import pytest

from eyenet.api.deps import CurrentUser
from eyenet.api.deps_paging import CursorParams
from eyenet.api.v1.actors.api_get_timeline import actors_timeline
from eyenet.contracts.enums import GroupKind, SourceKind
from eyenet.models.message import MessageTable
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


async def _seed_message(storage: BaseRepository) -> UUID:
    src = await storage.upsert_source(kind=SourceKind.TELEGRAM, display_name="tg", created_at=_NOW)
    grp = await storage.upsert_group(
        source_id=src, platform_groupid="@g", kind=GroupKind.CHAT, title="g", seen_at=_NOW
    )
    actor = await storage.upsert_actor(
        source_id=src,
        actor_key="tg:a",
        platform_userid="1",
        handle="@a",
        display_name="A",
        seen_at=_NOW,
    )
    await storage.put_message(
        MessageTable(
            source_id=src,
            group_id=grp,
            actor_id=actor,
            platform_msgid="1",
            evidence_ref="tg:1",
            body="hello world",
            length_chars=11,
            length_words=2,
            sent_at_source=_NOW,
            ingested_at=_NOW,
        )
    )
    return actor


async def test_kind_message_returns_messages_only(
    storage: BaseRepository, mkuser: Callable[..., CurrentUser]
) -> None:
    actor = await _seed_message(storage)
    page = CursorParams(offset=0, limit=50, include_total=True)
    res = await actors_timeline(actor, mkuser(), storage, page, None, None, "message")
    assert [e.kind for e in res.items] == ["message"]
    assert res.estimated_total == 1


async def test_kind_observation_excludes_messages(
    storage: BaseRepository, mkuser: Callable[..., CurrentUser]
) -> None:
    actor = await _seed_message(storage)
    page = CursorParams(offset=0, limit=50, include_total=True)
    res = await actors_timeline(actor, mkuser(), storage, page, None, None, "observation")
    assert res.items == []
    assert res.estimated_total == 0  # no observations, messages excluded by filter


async def test_kind_none_includes_messages(
    storage: BaseRepository, mkuser: Callable[..., CurrentUser]
) -> None:
    actor = await _seed_message(storage)
    page = CursorParams(offset=0, limit=50, include_total=True)
    res = await actors_timeline(actor, mkuser(), storage, page, None, None, None)
    assert len(res.items) == 1
