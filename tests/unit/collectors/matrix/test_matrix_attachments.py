"""M8: attachment download + persistence + E2EE Megolm decrypt."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from sqlmodel import Session, select

from eyenet.bus import MemoryBus
from eyenet.collectors.matrix import real as matrix_real
from eyenet.collectors.matrix.real import MatrixCollector
from eyenet.contracts.enums import AttachmentKind, SourceKind
from eyenet.contracts.raw_message import RawMessageEnvelope
from eyenet.identity_pool import FileIdentityPool, IdentityFile, IdentityFileEntry
from eyenet.identity_pool.loader import dump
from eyenet.models import AttachmentTable
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

from .test_matrix_collector_unit import _FakeAsyncClient, _FakeRoom


@dataclass
class _FakeDownloadResponse:
    body: bytes


@dataclass
class _FakeMediaEvent:
    event_id: str
    sender: str
    server_timestamp: int
    body: str = "file.bin"
    source: dict[str, Any] = field(default_factory=dict)


@dataclass
class _FakeMegolmEvent:
    event_id: str
    sender: str
    server_timestamp: int
    session_id: str = "session-x"
    source: dict[str, Any] = field(default_factory=dict)


async def _setup_collector(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[MatrixCollector, MemoryBus, BaseRepository, list[bytes]]:
    monkeypatch.setattr(matrix_real, "AsyncClient", _FakeAsyncClient)
    entry = IdentityFileEntry(
        name="alpha_mx",
        source=SourceKind.MATRIX,
        cooldown_seconds=0,
        matrix_homeserver_url="https://example.org",
        matrix_user_id="@alpha_mx:example.org",
        matrix_access_token="secret",
        matrix_monitor_rooms=["!room:example.org"],
    )
    cfg_path = tmp_path / "identities.toml"
    dump(IdentityFile(identities=[entry]), cfg_path)
    pool = FileIdentityPool(cfg_path)
    bus = MemoryBus()
    storage = get_repository(data_dir=tmp_path / "data")
    captured: list[bytes] = []

    async def _recorder(_subject: str, payload: bytes, _h: dict[str, str]) -> None:
        captured.append(payload)

    await bus.subscribe("raw.message.>", _recorder)
    coll = MatrixCollector(bus=bus, storage=storage, pool=pool, identity_name="alpha_mx")
    return coll, bus, storage, captured


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cleartext_image_attachment_downloaded_and_persisted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    coll, _bus, storage, captured = await _setup_collector(tmp_path, monkeypatch)
    await coll.on_subscribe()
    fake = coll._client
    assert isinstance(fake, _FakeAsyncClient)
    payload = b"\x89PNG\r\n\x1a\nfake-png-bytes"
    fake._download_response = _FakeDownloadResponse(body=payload)

    room = _FakeRoom(room_id="!room:example.org")
    event = _FakeMediaEvent(
        event_id="$pic1",
        sender="@bob:example.org",
        server_timestamp=1_716_000_000_000,
        body="screenshot.png",
        source={
            "content": {
                "msgtype": "m.image",
                "body": "screenshot.png",
                "url": "mxc://example.org/abc123",
                "info": {"mimetype": "image/png", "size": len(payload)},
            }
        },
    )
    # Use the RoomMessageImage isinstance check inside the collector: we
    # bypass it by directly calling _ingest_media_event (the per-kind
    # dispatcher).
    await coll._ingest_media_event(room, event)

    async with storage.session() as s:
        _res = await s.exec(select(AttachmentTable))
        rows = _res.all()
        assert len(rows) == 1
        row = rows[0]
        assert row.kind == AttachmentKind.IMAGE
        assert row.mime == "image/png"
        assert row.size_bytes == len(payload)
        assert row.storage_uri is not None
        storage_uri = row.storage_uri
    blob = Path(storage_uri).read_bytes()  # noqa: ASYNC240 — local fs read in test
    assert blob == payload

    # Envelope published with has_attachment=True.
    envs = [RawMessageEnvelope.model_validate_json(p) for p in captured]
    assert any(e.has_attachment and e.platform_msgid == "$pic1" for e in envs)

    await coll.shutdown()
    await storage.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_attachment_with_failing_integrity_flags_source_specific(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Encrypted attachment whose announced sha256 doesn't match → flagged."""
    from eyenet.models import MessageTable

    coll, _bus, storage, _captured = await _setup_collector(tmp_path, monkeypatch)
    await coll.on_subscribe()
    fake = coll._client
    assert isinstance(fake, _FakeAsyncClient)
    fake._download_response = _FakeDownloadResponse(body=b"ciphertext")

    # Monkeypatch decrypt_attachment to return predictable plaintext;
    # the descriptor announces a hash that won't match → integrity_ok=False.
    monkeypatch.setattr(matrix_real, "decrypt_attachment", lambda *_a, **_kw: b"plain-bytes")

    room = _FakeRoom(room_id="!room:example.org")
    event = _FakeMediaEvent(
        event_id="$enc1",
        sender="@bob:example.org",
        server_timestamp=1_716_000_000_000,
        body="enc.bin",
        source={
            "content": {
                "msgtype": "m.file",
                "body": "enc.bin",
                "file": {
                    "url": "mxc://example.org/enc1",
                    "key": {"k": "AAAA", "alg": "A256CTR"},
                    "iv": "AAAA",
                    "hashes": {"sha256": "deliberately-wrong-hash"},
                },
                "info": {"mimetype": "application/octet-stream", "size": 10},
            }
        },
    )
    await coll._ingest_media_event(room, event)

    async with storage.session() as s:
        _res = await s.exec(select(MessageTable).where(MessageTable.platform_msgid == "$enc1"))
        msg = _res.first()
        assert msg is not None
        assert msg.source_specific.get("attachment_integrity_failed") is True
        _res = await s.exec(select(AttachmentTable))
        atts = _res.all()
        # Attachment row exists but storage_uri is None (blob NOT persisted
        # because integrity check failed).
        assert len(atts) == 1
        assert atts[0].storage_uri is None

    await coll.shutdown()
    await storage.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_megolm_decrypt_failure_emits_sentinel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    coll, _bus, storage, captured = await _setup_collector(tmp_path, monkeypatch)
    await coll.on_subscribe()
    fake = coll._client
    assert isinstance(fake, _FakeAsyncClient)
    # decrypt_event returns None → sentinel path.
    fake._decrypt_map = {}

    room = _FakeRoom(room_id="!room:example.org")
    event = _FakeMegolmEvent(
        event_id="$enc_msg",
        sender="@bob:example.org",
        server_timestamp=1_716_000_000_000,
    )
    await coll._on_megolm(room, event)

    envs = [RawMessageEnvelope.model_validate_json(p) for p in captured]
    sentinels = [e for e in envs if e.platform_msgid == "$enc_msg"]
    assert len(sentinels) == 1
    s = sentinels[0]
    assert s.length_chars == 0
    assert s.length_words == 0
    assert s.has_attachment is False

    await coll.shutdown()
    await storage.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_megolm_decrypt_success_routes_to_text_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nio.events import RoomMessageText as _RealRoomMessageText

    coll, _bus, storage, captured = await _setup_collector(tmp_path, monkeypatch)
    await coll.on_subscribe()
    fake = coll._client
    assert isinstance(fake, _FakeAsyncClient)

    inner = _RealRoomMessageText.from_dict(
        {
            "event_id": "$plain1",
            "sender": "@bob:example.org",
            "origin_server_ts": 1_716_000_000_000,
            "type": "m.room.message",
            "content": {"msgtype": "m.text", "body": "decrypted body"},
        }
    )
    fake._decrypt_map = {"$enc_msg": inner}

    room = _FakeRoom(room_id="!room:example.org")
    encrypted = _FakeMegolmEvent(
        event_id="$enc_msg",
        sender="@bob:example.org",
        server_timestamp=1_716_000_000_000,
    )
    await coll._on_megolm(room, encrypted)

    envs = [RawMessageEnvelope.model_validate_json(p) for p in captured]
    decrypted = [e for e in envs if e.platform_msgid == "$plain1"]
    assert len(decrypted) == 1
    assert decrypted[0].length_chars == len("decrypted body")

    await coll.shutdown()
    await storage.close()
