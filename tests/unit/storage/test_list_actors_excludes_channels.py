# SPDX-License-Identifier: AGPL-3.0-or-later
"""list_actors / count_actors exclude channel senders (negative -100 peer ids)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from eyenet.contracts.enums import SourceKind
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


@pytest.mark.unit
async def test_channels_excluded_from_actor_roster(storage: BaseRepository) -> None:
    now = datetime.now(tz=UTC)
    src = await storage.upsert_source(kind=SourceKind.TELEGRAM, display_name="tg", created_at=now)

    async def _actor(uid: str, disp: str) -> None:
        await storage.upsert_actor(
            source_id=src,
            actor_key=f"actor:{uid}",
            platform_userid=uid,
            handle=None,
            display_name=disp,
            seen_at=now,
        )

    await _actor("8595058147", "Nicole Lee")  # individual
    await _actor("555", "Bob")  # individual (a forwarded person)
    await _actor("-1003573398394", "Some Channel")  # channel-broadcast
    await _actor("-1003928209947", "Other Channel")  # channel

    rows = await storage.list_actors(limit=50)
    uids = {r.platform_userid for r in rows}
    assert uids == {"8595058147", "555"}  # channels excluded
    assert await storage.count_actors() == 2
