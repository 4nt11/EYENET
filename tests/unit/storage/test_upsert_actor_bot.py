# SPDX-License-Identifier: AGPL-3.0-or-later
"""upsert_actor carries + sticks the Telegram bot flag (is_bot_self_declared)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from eyenet.contracts.enums import SourceKind
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


async def _upsert(storage: BaseRepository, key: str, *, is_bot: bool):
    src = await storage.upsert_source(kind=SourceKind.TELEGRAM, display_name="tg", created_at=_NOW)
    aid = await storage.upsert_actor(
        source_id=src, actor_key=key, platform_userid=key[-6:], handle="@x",
        display_name="X", seen_at=_NOW, is_bot=is_bot,
    )
    return await storage.get_actor(aid)


async def test_bot_flag_set_on_create(storage: BaseRepository) -> None:
    row = await _upsert(storage, "tg:bot", is_bot=True)
    assert row.is_bot_self_declared is True


async def test_default_is_not_bot(storage: BaseRepository) -> None:
    row = await _upsert(storage, "tg:human", is_bot=False)
    assert row.is_bot_self_declared is False


async def test_bot_flag_is_sticky(storage: BaseRepository) -> None:
    # First sight: bot. A later plain-post upsert must NOT clear the flag.
    src = await storage.upsert_source(kind=SourceKind.TELEGRAM, display_name="tg", created_at=_NOW)
    aid = await storage.upsert_actor(
        source_id=src, actor_key="tg:sticky", platform_userid="1", handle="@b",
        display_name="B", seen_at=_NOW, is_bot=True,
    )
    await storage.upsert_actor(
        source_id=src, actor_key="tg:sticky", platform_userid="1", handle="@b",
        display_name="B", seen_at=_NOW, is_bot=False,
    )
    row = await storage.get_actor(aid)
    assert row.is_bot_self_declared is True
