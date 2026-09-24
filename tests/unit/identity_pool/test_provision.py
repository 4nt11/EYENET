"""Unit tests for the single identity-provisioning path (encrypt + persist)."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from telethon.crypto import AuthKey
from telethon.sessions import SQLiteSession, StringSession

from eyenet.contracts.enums import SourceKind
from eyenet.crypto import decrypt_session, load_session_key
from eyenet.identity_pool._provision import (
    SessionValidationError,
    provision_identity,
    provision_identity_from_session,
)
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository


def _fake_session_blob(tmp_path: Path) -> bytes:
    """A structurally-real Telegram .session (auth_key + DC), no network."""
    name = str(tmp_path / "mint")
    sess = SQLiteSession(name)
    sess.set_dc(2, "149.154.167.51", 443)
    sess.auth_key = AuthKey(bytes(range(256)))
    sess.save()
    sess.close()
    return (tmp_path / "mint.session").read_bytes()


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


@pytest.mark.unit
async def test_provision_encrypts_and_persists(storage: BaseRepository, tmp_path: Path) -> None:
    blob = _fake_session_blob(tmp_path)
    session_key = load_session_key(tmp_path)
    source_id = uuid.uuid4()

    row = await provision_identity(
        storage=storage,
        session_key=session_key,
        data_dir=tmp_path,
        name="tg_alpha",
        source_id=source_id,
        source_kind=SourceKind.TELEGRAM,
        secret_blob=blob,
        source_config={"telegram_api_id": 42, "telegram_api_hash": "deadbeef"},
    )

    assert row.name == "tg_alpha"
    assert row.source_config == {"telegram_api_id": 42, "telegram_api_hash": "deadbeef"}

    # Blob on disk must be ciphertext, NOT a readable SQLite session.
    on_disk = Path(row.session_path).read_bytes()
    assert on_disk[:6] != b"SQLite", "session blob must not be plaintext SQLite"
    assert Path(row.session_path).stat().st_mode & 0o777 == 0o600

    # And it must decrypt back into a usable StringSession with the same auth_key.
    string = decrypt_session(session_key, on_disk)
    restored = StringSession(string)
    assert restored.auth_key.key == bytes(range(256))
    assert restored.dc_id == 2


@pytest.mark.unit
async def test_provision_rejects_garbage_blob(storage: BaseRepository, tmp_path: Path) -> None:
    session_key = load_session_key(tmp_path)
    with pytest.raises(SessionValidationError, match="not_a_valid_session_file"):
        await provision_identity(
            storage=storage,
            session_key=session_key,
            data_dir=tmp_path,
            name="bad",
            source_id=uuid.uuid4(),
            source_kind=SourceKind.TELEGRAM,
            secret_blob=b"this is not a sqlite database",
            source_config={},
        )


@pytest.mark.unit
async def test_provision_rejects_unsupported_source(
    storage: BaseRepository, tmp_path: Path
) -> None:
    session_key = load_session_key(tmp_path)
    with pytest.raises(SessionValidationError, match="not supported for source"):
        await provision_identity(
            storage=storage,
            session_key=session_key,
            data_dir=tmp_path,
            name="m1",
            source_id=uuid.uuid4(),
            source_kind=SourceKind.MATRIX,
            secret_blob=b"whatever",
            source_config={},
        )


@pytest.mark.unit
async def test_provision_from_session_string_encrypts_and_persists(
    storage: BaseRepository, tmp_path: Path
) -> None:
    """The QR path hands in a live StringSession string, not a blob to convert."""
    session_key = load_session_key(tmp_path)
    string = StringSession.save(StringSession())  # any portable session string

    row = await provision_identity_from_session(
        storage=storage,
        session_key=session_key,
        data_dir=tmp_path,
        name="tg_qr",
        source_id=uuid.uuid4(),
        session_string=string,
        source_config={"telegram_api_id": 7, "telegram_api_hash": "h"},
    )

    assert row.source_config == {"telegram_api_id": 7, "telegram_api_hash": "h"}
    on_disk = Path(row.session_path).read_bytes()
    assert on_disk[:6] != b"SQLite"  # ciphertext, not a raw session
    assert decrypt_session(session_key, on_disk) == string  # round-trips
