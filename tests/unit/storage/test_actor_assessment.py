# SPDX-License-Identifier: AGPL-3.0-or-later
"""set_actor_assessment / actor_aliases (ActorsMixin dossier writes/reads)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from eyenet.contracts.enums import SourceKind
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


async def _seed(storage: BaseRepository):
    source_id = await storage.upsert_source(
        kind=SourceKind.TELEGRAM, display_name="tg", created_at=_NOW
    )
    return await storage.upsert_actor(
        source_id=source_id, actor_key="a:1", platform_userid="1",
        handle="h", display_name=None, seen_at=_NOW,
    )


async def test_set_assessment_roundtrip(storage: BaseRepository) -> None:
    actor_id = await _seed(storage)
    assert await storage.set_actor_assessment(actor_id, "watch closely") is True
    row = await storage.get_actor(actor_id)
    assert row.operator_assessment == "watch closely"  # type: ignore[attr-defined]


async def test_set_assessment_unknown_actor(storage: BaseRepository) -> None:
    assert await storage.set_actor_assessment(uuid4(), "x") is False


async def test_actor_aliases_empty(storage: BaseRepository) -> None:
    actor_id = await _seed(storage)
    assert await storage.actor_aliases(actor_id) == []
