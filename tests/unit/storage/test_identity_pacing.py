# SPDX-License-Identifier: AGPL-3.0-or-later
"""update_identity_pacing — edit the cooldown + notes identity COLUMNS in place."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from eyenet.contracts.enums import SourceKind
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


async def test_update_pacing_writes_only_provided_fields(storage: BaseRepository) -> None:
    src_id = await storage.upsert_source(
        kind=SourceKind.DISCORD, display_name="d", created_at=datetime.now(tz=UTC)
    )
    ident = await storage.create_identity(
        name="id1", source_id=src_id, session_path="", cooldown_seconds=21_600, notes="orig"
    )

    # Change only the cooldown — notes must be untouched.
    row = await storage.update_identity_pacing(identity_id=ident.id, cooldown_seconds=600)
    assert row.cooldown_seconds == 600
    assert row.notes == "orig"

    # Change only the notes — cooldown must be untouched.
    row = await storage.update_identity_pacing(identity_id=ident.id, notes="updated")
    assert row.notes == "updated"
    assert row.cooldown_seconds == 600


async def test_update_pacing_missing_identity_raises(storage: BaseRepository) -> None:
    from uuid import uuid4

    with pytest.raises(ValueError, match="not found"):
        await storage.update_identity_pacing(identity_id=uuid4(), cooldown_seconds=1)
