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


async def test_provision_encrypts_telegram_session_on_import(
    storage: BaseRepository, tmp_path: Path
) -> None:
    """With session_key + data_dir, an imported Telegram identity's plaintext
    .session is encrypted at rest and the DB row is collector-openable."""
    from telethon.crypto import AuthKey
    from telethon.sessions import SQLiteSession, StringSession

    from eyenet.crypto import decrypt_session, load_session_key

    mint = str(tmp_path / "tg_import")
    sess = SQLiteSession(mint)
    sess.set_dc(2, "149.154.167.51", 443)
    sess.auth_key = AuthKey(bytes(range(256)))
    sess.save()
    sess.close()

    entry = IdentityFileEntry(
        name="tg_import",
        source=SourceKind.TELEGRAM,
        session_path=mint + ".session",
        telegram_api_id=99,
        telegram_api_hash="hh",
        monitor_groups=["@x"],
    )
    key = load_session_key(tmp_path)
    result = await provision_identities(
        storage, IdentityFile(identities=[entry]), now=_NOW, session_key=key, data_dir=tmp_path
    )
    assert result.created == ["tg_import"]

    row = next(i for i in await storage.list_identities() if i.name == "tg_import")
    assert row.source_config == {
        "telegram_api_id": 99,
        "telegram_api_hash": "hh",
        "monitor_groups": ["@x"],
    }
    # The stored blob is ciphertext under <data_dir>/identities/, not the TOML path.
    assert row.session_path != entry.session_path
    on_disk = Path(row.session_path).read_bytes()
    assert on_disk[:6] != b"SQLite"
    restored = StringSession(decrypt_session(key, on_disk))
    assert restored.auth_key.key == bytes(range(256))


def test_loader_role_round_trips(tmp_path: Path) -> None:
    pool = IdentityFile(identities=[_entry("scout1", role=IdentityRole.SCOUT), _entry("mon1")])
    path = tmp_path / "identities.toml"
    dump(pool, path)
    loaded = load(path, check_session_files=False)
    roles = {e.name: e.role for e in loaded.identities}
    assert roles["scout1"] is IdentityRole.SCOUT
    assert roles["mon1"] is None
