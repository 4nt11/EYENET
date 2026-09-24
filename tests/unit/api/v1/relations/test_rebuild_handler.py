# SPDX-License-Identifier: AGPL-3.0-or-later
"""Direct-call unit test for POST /v1/relations/rebuild."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from eyenet.api.deps import CurrentUser
from eyenet.api.v1.relations.api_rebuild import relations_rebuild
from eyenet.contracts.enums import GroupKind, SourceKind
from eyenet.models.message import MessageTable
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


async def test_rebuild_returns_edge_count(
    storage: BaseRepository, mkuser: Callable[..., CurrentUser]
) -> None:
    src = await storage.upsert_source(kind=SourceKind.TELEGRAM, display_name="tg", created_at=_NOW)
    grp = await storage.upsert_group(
        source_id=src, platform_groupid="@g", kind=GroupKind.CHAT, title="g", seen_at=_NOW
    )
    a = await storage.upsert_actor(
        source_id=src,
        actor_key="tg:a",
        platform_userid="1",
        handle="@aaa",
        display_name="A",
        seen_at=_NOW,
    )
    b = await storage.upsert_actor(
        source_id=src,
        actor_key="tg:b",
        platform_userid="2",
        handle="@bbb",
        display_name="B",
        seen_at=_NOW,
    )
    assert b  # keep b referenced
    await storage.put_message(
        MessageTable(
            source_id=src,
            group_id=grp,
            actor_id=a,
            platform_msgid="1",
            evidence_ref="tg:1",
            body="yo @bbb",
            length_chars=7,
            length_words=2,
            sent_at_source=_NOW,
            ingested_at=_NOW,
        )
    )
    res = await relations_rebuild(mkuser(), storage)
    assert res.edges == 1


async def test_rebuild_empty_corpus(
    storage: BaseRepository, mkuser: Callable[..., CurrentUser]
) -> None:
    res = await relations_rebuild(mkuser(), storage)
    assert res.edges == 0
