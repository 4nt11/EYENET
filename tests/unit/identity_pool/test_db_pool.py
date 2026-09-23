"""Unit tests for the DB-backed identity pool (claim/release/freeze + rebuild)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from eyenet.contracts.enums import IdentityState, SourceKind
from eyenet.identity_pool.db import DbIdentityPool
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


async def _seed_identity(storage: BaseRepository, *, state: IdentityState) -> str:
    source_id = await storage.upsert_source(
        kind=SourceKind.TELEGRAM, display_name="tg", created_at=datetime.now(tz=UTC)
    )
    row = await storage.create_identity(
        name="tg_alpha",
        source_id=source_id,
        session_path="/data/identities/abc.enc",
        source_config={"telegram_api_id": 7, "telegram_api_hash": "h", "monitor_groups": ["@g"]},
    )
    if state != IdentityState.AVAILABLE:
        await storage.set_identity_state(identity_id=row.id, state=state)
    return row.name


@pytest.mark.unit
async def test_claim_rebuilds_entry_from_source_config(storage: BaseRepository) -> None:
    name = await _seed_identity(storage, state=IdentityState.AVAILABLE)
    pool = DbIdentityPool(storage)

    entry = await pool.claim(name)

    # Reconstructed IdentityFileEntry the collector consumes, source_config splatted.
    assert entry.name == "tg_alpha"
    assert entry.source == SourceKind.TELEGRAM
    assert entry.session_path == "/data/identities/abc.enc"
    assert entry.telegram_api_id == 7
    assert entry.telegram_api_hash == "h"
    assert entry.monitor_groups == ["@g"]
    assert entry.state == IdentityState.IN_USE  # flipped by claim


@pytest.mark.unit
async def test_claim_rejects_in_use(storage: BaseRepository) -> None:
    name = await _seed_identity(storage, state=IdentityState.IN_USE)
    pool = DbIdentityPool(storage)
    with pytest.raises(RuntimeError, match="already in use"):
        await pool.claim(name)


@pytest.mark.unit
async def test_claim_rejects_burned(storage: BaseRepository) -> None:
    name = await _seed_identity(storage, state=IdentityState.BURNED)
    pool = DbIdentityPool(storage)
    with pytest.raises(RuntimeError, match="burned"):
        await pool.claim(name)


@pytest.mark.unit
async def test_unknown_identity_raises_keyerror(storage: BaseRepository) -> None:
    pool = DbIdentityPool(storage)
    with pytest.raises(KeyError, match="unknown identity"):
        await pool.claim("nope")


@pytest.mark.unit
async def test_release_persists_new_state(storage: BaseRepository) -> None:
    name = await _seed_identity(storage, state=IdentityState.AVAILABLE)
    pool = DbIdentityPool(storage)
    await pool.claim(name)
    await pool.release(name, new_state=IdentityState.AVAILABLE)
    row = await storage.get_identity_by_name(name)
    assert row is not None
    assert row.state == IdentityState.AVAILABLE
    assert row.last_used_at is not None


@pytest.mark.unit
async def test_freeze_all(storage: BaseRepository) -> None:
    name = await _seed_identity(storage, state=IdentityState.AVAILABLE)
    pool = DbIdentityPool(storage)
    await pool.freeze_all()
    row = await storage.get_identity_by_name(name)
    assert row is not None
    assert row.state == IdentityState.FROZEN
