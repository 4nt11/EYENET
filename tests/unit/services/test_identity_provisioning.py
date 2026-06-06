# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for the file↔DB identity bridge (M9.E5, Slice E4)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from eyenet.contracts.enums import IdentityRole, SourceKind
from eyenet.identity_pool.loader import IdentityFile, IdentityFileEntry, dump, load
from eyenet.services.discovery.identity_provisioning import provision_identities
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 6, 6, tzinfo=UTC)


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


def _entry(name: str, *, role: IdentityRole | None = None) -> IdentityFileEntry:
    return IdentityFileEntry(
        name=name, source=SourceKind.TELEGRAM, session_path=f"/{name}", role=role
    )


async def test_provision_creates_scout_and_monitor(storage: BaseRepository) -> None:
    pool = IdentityFile(identities=[_entry("scout1", role=IdentityRole.SCOUT), _entry("mon1")])
    result = await provision_identities(storage, pool, now=_NOW)
    assert set(result.created) == {"scout1", "mon1"}

    by_name = {i.name: i for i in await storage.list_identities()}
    assert by_name["scout1"].role is IdentityRole.SCOUT
    assert by_name["mon1"].role is IdentityRole.MONITOR
    # The discovery loop can now lease a scout.
    assert await storage.has_available_scout(by_name["scout1"].source_id) is True


async def test_provision_is_idempotent(storage: BaseRepository) -> None:
    pool = IdentityFile(identities=[_entry("scout1", role=IdentityRole.SCOUT)])
    await provision_identities(storage, pool, now=_NOW)
    again = await provision_identities(storage, pool, now=_NOW)
    assert again.created == []
    assert again.unchanged == ["scout1"]


async def test_provision_updates_role(storage: BaseRepository) -> None:
    await provision_identities(storage, IdentityFile(identities=[_entry("x")]), now=_NOW)
    result = await provision_identities(
        storage, IdentityFile(identities=[_entry("x", role=IdentityRole.SCOUT)]), now=_NOW
    )
    assert result.updated == ["x"]
    (row,) = await storage.list_identities()
    assert row.role is IdentityRole.SCOUT


def test_loader_role_round_trips(tmp_path: Path) -> None:
    pool = IdentityFile(identities=[_entry("scout1", role=IdentityRole.SCOUT), _entry("mon1")])
    path = tmp_path / "identities.toml"
    dump(pool, path)
    loaded = load(path, check_session_files=False)
    roles = {e.name: e.role for e in loaded.identities}
    assert roles["scout1"] is IdentityRole.SCOUT
    assert roles["mon1"] is None
