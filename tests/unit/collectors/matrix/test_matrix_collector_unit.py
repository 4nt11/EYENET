"""`MatrixCollector` (real) — unit tests with a fake nio AsyncClient.

We don't reach out to a real homeserver here. The fake client implements
just enough of the nio surface that `on_subscribe` and `_ingest_event` can
run their full paths: callback registration, room alias resolution, the
sync loop coroutine, and clean shutdown.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from eyenet.bus import MemoryBus
from eyenet.collectors.matrix import real as matrix_real
from eyenet.collectors.matrix.real import MatrixCollector, _missing_matrix_fields
from eyenet.contracts.enums import SourceKind
from eyenet.contracts.raw_message import RawMessageEnvelope
from eyenet.identity_pool import FileIdentityPool, IdentityFile, IdentityFileEntry
from eyenet.identity_pool.loader import dump
from eyenet.storage import SQLiteStorage

# --- fake nio surface ----------------------------------------------------


@dataclass
class _FakeRoom:
    """Structural stand-in for nio.MatrixRoom.

    IMPORTANT: mirror real nio's split between properties and methods.
    `display_name` and `machine_name` are PROPERTIES; `named_room_name`
    and `group_name` are METHODS. The collector code MUST access them
    accordingly — a previous regression treated `named_room_name` as an
    attribute and SQLAlchemy choked on the bound method.
    """

    room_id: str
    _display_name: str | None = "Test Room"

    def user_name(self, _user_id: str) -> str | None:
        return "Display Name"

    @property
    def display_name(self) -> str:
        return self._display_name or self.room_id

    @property
    def machine_name(self) -> str:
        return self.room_id

    def named_room_name(self) -> str | None:
        return self._display_name

    def group_name(self) -> str:
        return self.display_name


@dataclass
class _FakeTextEvent:
    event_id: str
    sender: str
    server_timestamp: int  # ms epoch
    body: str


class _FakeAsyncClient:
    """Stand-in for nio.AsyncClient covering only what MatrixCollector uses."""

    def __init__(
        self,
        homeserver: str,
        user_id: str,
        device_id: str | None = None,
        *,
        store_path: str | None = None,
        config: Any | None = None,
        **_extra: Any,
    ) -> None:
        self.homeserver = homeserver
        self.user_id = user_id
        self.device_id = device_id
        self.store_path = store_path
        self.config = config
        self.access_token: str | None = None
        self.callbacks: list[Any] = []
        self.rooms: dict[str, _FakeRoom] = {}
        self._sync_started = asyncio.Event()
        self._sync_stop = asyncio.Event()
        self.last_sync_kwargs: dict[str, Any] = {}
        self._decrypt_map: dict[str, Any] = {}
        # Tests override these to simulate failure modes.
        self.whoami_response_user_id: str | None = None
        self.whoami_should_error: bool = False
        self.whoami_should_raise: bool = False
        # Override to script download responses for media tests.
        self._download_response: Any = None

    def add_event_callback(self, cb: Any, _filter: Any) -> None:
        self.callbacks.append(cb)

    async def load_store(self) -> None:
        return None

    async def download(self, _server: str, _media_id: str) -> Any:
        return self._download_response

    def decrypt_event(self, event: Any) -> Any:
        # Tests assign `_decrypt_map` mapping event_id -> decrypted event.
        decrypt_map: dict[str, Any] = getattr(self, "_decrypt_map", {})
        event_id = getattr(event, "event_id", None)
        if event_id is None:
            return None
        return decrypt_map.get(event_id)

    async def whoami(self) -> Any:
        from nio.responses import WhoamiError, WhoamiResponse

        if self.whoami_should_raise:
            raise ConnectionError("simulated network failure")
        if self.whoami_should_error:
            return WhoamiError(message="M_UNKNOWN_TOKEN", status_code="401")
        return WhoamiResponse(
            user_id=self.whoami_response_user_id or self.user_id,
            device_id=self.device_id,
            is_guest=False,
        )

    async def room_resolve_alias(self, alias: str) -> Any:
        # Map any #foo:server alias to a deterministic !foo:server room id.
        from nio.responses import RoomResolveAliasResponse

        room_id = "!" + alias.lstrip("#").split(":")[0] + ":example.org"
        return RoomResolveAliasResponse(room_alias=alias, room_id=room_id, servers=["example.org"])

    async def sync_forever(self, **kwargs: Any) -> None:
        self.last_sync_kwargs = kwargs
        self._sync_started.set()
        await self._sync_stop.wait()

    async def sync(self, **_kwargs: Any) -> Any:
        # Tests assign `_sync_response` to control the shape returned.
        return getattr(self, "_sync_response", None)

    async def room_messages(self, room_id: str, **_kwargs: Any) -> Any:
        # Tests assign `_messages_pages` as a list of responses, one per call.
        pages: list[Any] = getattr(self, "_messages_pages", [])
        if not pages:
            from nio.responses import RoomMessagesResponse

            return RoomMessagesResponse(room_id=room_id, chunk=[], start="", end=None)
        return pages.pop(0)

    async def close(self) -> None:
        self._sync_stop.set()


# --- pool helpers --------------------------------------------------------


def _setup_pool(tmp_path: Path, name: str, *, missing: set[str] | None = None) -> Path:
    fields: dict[str, Any] = {
        "matrix_homeserver_url": "https://example.org",
        "matrix_user_id": f"@{name}:example.org",
        "matrix_access_token": "secret",
        "matrix_device_id": "EYENET01",
        "matrix_monitor_rooms": ["!room:example.org", "#alias:example.org"],
    }
    for f in missing or set():
        fields[f] = None
    entry = IdentityFileEntry(
        name=name,
        source=SourceKind.MATRIX,
        cooldown_seconds=0,
        **fields,
    )
    cfg_path = tmp_path / "identities.toml"
    dump(IdentityFile(identities=[entry]), cfg_path)
    return cfg_path


# --- tests --------------------------------------------------------------


@pytest.mark.unit
def test_missing_matrix_fields_helper() -> None:
    base = {
        "name": "x",
        "source": SourceKind.MATRIX,
        "matrix_homeserver_url": "https://h",
        "matrix_user_id": "@u:h",
        "matrix_access_token": "t",
    }
    assert _missing_matrix_fields(IdentityFileEntry(**base)) == []  # type: ignore[arg-type]
    no_host = dict(base, matrix_homeserver_url=None)
    assert _missing_matrix_fields(IdentityFileEntry(**no_host)) == [  # type: ignore[arg-type]
        "matrix_homeserver_url"
    ]
    no_token = dict(base, matrix_access_token=None)
    assert "matrix_access_token" in _missing_matrix_fields(
        IdentityFileEntry(**no_token)  # type: ignore[arg-type]
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_on_subscribe_raises_when_required_fields_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(matrix_real, "AsyncClient", _FakeAsyncClient)
    cfg_path = _setup_pool(tmp_path, "alpha_mx", missing={"matrix_access_token"})
    pool = FileIdentityPool(cfg_path)
    bus = MemoryBus()
    storage = SQLiteStorage(tmp_path / "data")
    coll = MatrixCollector(bus=bus, storage=storage, pool=pool, identity_name="alpha_mx")
    with pytest.raises(ValueError, match="matrix_access_token"):
        await coll.on_subscribe()
    await storage.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_on_subscribe_raises_when_token_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A WhoamiError from the homeserver must fail-fast, not enter sync_forever."""

    class _RejectingClient(_FakeAsyncClient):
        def __init__(self, *a: Any, **kw: Any) -> None:
            super().__init__(*a, **kw)
            self.whoami_should_error = True

    monkeypatch.setattr(matrix_real, "AsyncClient", _RejectingClient)
    cfg_path = _setup_pool(tmp_path, "alpha_mx")
    pool = FileIdentityPool(cfg_path)
    bus = MemoryBus()
    storage = SQLiteStorage(tmp_path / "data")
    coll = MatrixCollector(bus=bus, storage=storage, pool=pool, identity_name="alpha_mx")
    with pytest.raises(ValueError, match="matrix_access_token rejected"):
        await coll.on_subscribe()
    await storage.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_on_subscribe_raises_when_user_id_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The token's user_id must match matrix_user_id from the TOML."""

    class _WrongUserClient(_FakeAsyncClient):
        def __init__(self, *a: Any, **kw: Any) -> None:
            super().__init__(*a, **kw)
            self.whoami_response_user_id = "@someone_else:example.org"

    monkeypatch.setattr(matrix_real, "AsyncClient", _WrongUserClient)
    cfg_path = _setup_pool(tmp_path, "alpha_mx")
    pool = FileIdentityPool(cfg_path)
    bus = MemoryBus()
    storage = SQLiteStorage(tmp_path / "data")
    coll = MatrixCollector(bus=bus, storage=storage, pool=pool, identity_name="alpha_mx")
    with pytest.raises(ValueError, match="does not match the token"):
        await coll.on_subscribe()
    await storage.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_on_subscribe_raises_on_homeserver_unreachable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A network/404 failure on whoami must fail-fast with a URL hint."""

    class _UnreachableClient(_FakeAsyncClient):
        def __init__(self, *a: Any, **kw: Any) -> None:
            super().__init__(*a, **kw)
            self.whoami_should_raise = True

    monkeypatch.setattr(matrix_real, "AsyncClient", _UnreachableClient)
    cfg_path = _setup_pool(tmp_path, "alpha_mx")
    pool = FileIdentityPool(cfg_path)
    bus = MemoryBus()
    storage = SQLiteStorage(tmp_path / "data")
    coll = MatrixCollector(bus=bus, storage=storage, pool=pool, identity_name="alpha_mx")
    with pytest.raises(ValueError, match="did not respond to"):
        await coll.on_subscribe()
    await storage.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_on_subscribe_wires_callbacks_and_resolves_aliases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(matrix_real, "AsyncClient", _FakeAsyncClient)
    cfg_path = _setup_pool(tmp_path, "alpha_mx")
    pool = FileIdentityPool(cfg_path)
    bus = MemoryBus()
    storage = SQLiteStorage(tmp_path / "data")
    coll = MatrixCollector(bus=bus, storage=storage, pool=pool, identity_name="alpha_mx")
    await coll.on_subscribe()

    fake = coll._client
    assert isinstance(fake, _FakeAsyncClient)
    # Access token plumbed through; no login round-trip.
    assert fake.access_token == "secret"  # noqa: S105 — test fixture
    # Nine callbacks registered: RoomMessageText, four media kinds,
    # ReactionEvent, MegolmEvent, BadEvent, UnknownBadEvent.
    assert len(fake.callbacks) == 9
    # Both forms resolved into the canonical !-prefixed set.
    assert coll._monitor_room_ids == {"!room:example.org", "!alias:example.org"}
    # OPSEC: sync was started with presence=offline.
    await asyncio.sleep(0)  # let sync_forever schedule
    assert fake._sync_started.is_set() or coll._sync_task is not None
    # Drain task and check kwargs.
    await coll.shutdown()
    assert fake.last_sync_kwargs.get("set_presence") == "offline"
    await storage.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ingest_event_publishes_envelope_and_persists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(matrix_real, "AsyncClient", _FakeAsyncClient)
    cfg_path = _setup_pool(tmp_path, "alpha_mx")
    pool = FileIdentityPool(cfg_path)
    bus = MemoryBus()
    storage = SQLiteStorage(tmp_path / "data")

    captured: list[tuple[str, bytes]] = []

    async def _recorder(subject: str, payload: bytes, _h: dict[str, str]) -> None:
        captured.append((subject, payload))

    await bus.subscribe("raw.message.>", _recorder)

    coll = MatrixCollector(bus=bus, storage=storage, pool=pool, identity_name="alpha_mx")
    await coll.on_subscribe()

    room = _FakeRoom(room_id="!room:example.org")
    event = _FakeTextEvent(
        event_id="$evt001",
        sender="@bob:example.org",
        server_timestamp=1_716_550_000_000,
        body="hello from bob",
    )
    # _FakeRoom / _FakeTextEvent are structural stand-ins for nio types.
    await coll._on_message(room, event)
    await asyncio.sleep(0)  # let publisher flush

    assert len(captured) == 1
    subject, payload = captured[0]
    assert subject == f"raw.message.matrix.{coll.instance_id}"
    env = RawMessageEnvelope.model_validate_json(payload)
    assert env.source == SourceKind.MATRIX
    assert env.evidence_ref == "matrix:!room:example.org:$evt001"
    assert env.platform_groupid == "!room:example.org"
    assert env.platform_msgid == "$evt001"
    assert env.length_chars == len("hello from bob")
    assert env.has_attachment is False
    assert env.reply_to_platform_msgid is None

    # Duplicate event delivery is a no-op for the message store, but the
    # collector still publishes (sensors use corpus cursors, not bus dedup).
    captured.clear()
    await coll._on_message(room, event)
    await asyncio.sleep(0)
    assert len(captured) == 1

    await coll.shutdown()
    await storage.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_backfill_refuses_without_monitor_rooms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--backfill with no matrix_monitor_rooms must fail-fast, not scrape all rooms."""
    monkeypatch.setattr(matrix_real, "AsyncClient", _FakeAsyncClient)

    # Build an identity with empty monitor_rooms.
    entry = IdentityFileEntry(
        name="alpha_mx",
        source=SourceKind.MATRIX,
        cooldown_seconds=0,
        matrix_homeserver_url="https://example.org",
        matrix_user_id="@alpha_mx:example.org",
        matrix_access_token="secret",  # noqa: S106 — test fixture
        matrix_monitor_rooms=[],
    )
    cfg_path = tmp_path / "identities.toml"
    dump(IdentityFile(identities=[entry]), cfg_path)
    pool = FileIdentityPool(cfg_path)
    bus = MemoryBus()
    storage = SQLiteStorage(tmp_path / "data")
    coll = MatrixCollector(
        bus=bus, storage=storage, pool=pool, identity_name="alpha_mx", backfill=True
    )
    with pytest.raises(ValueError, match="matrix_monitor_rooms"):
        await coll.on_subscribe()
    await storage.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_backfill_pages_room_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Backfill walks `/messages` pages until exhausted, ingesting text events."""
    from nio.events import RoomMessageText as _RealRoomMessageText
    from nio.responses import (
        RoomInfo,
        RoomMessagesResponse,
        Rooms,
        SyncResponse,
        Timeline,
    )

    def _build_text_event(
        event_id: str, sender: str, ts_ms: int, body: str
    ) -> _RealRoomMessageText:
        return _RealRoomMessageText.from_dict(
            {
                "event_id": event_id,
                "sender": sender,
                "origin_server_ts": ts_ms,
                "type": "m.room.message",
                "content": {"msgtype": "m.text", "body": body},
            }
        )

    monkeypatch.setattr(matrix_real, "AsyncClient", _FakeAsyncClient)
    cfg_path = _setup_pool(tmp_path, "alpha_mx")
    pool = FileIdentityPool(cfg_path)
    bus = MemoryBus()
    storage = SQLiteStorage(tmp_path / "data")

    captured: list[str] = []

    async def _recorder(subject: str, _p: bytes, _h: dict[str, str]) -> None:
        captured.append(subject)

    await bus.subscribe("raw.message.>", _recorder)

    coll = MatrixCollector(
        bus=bus,
        storage=storage,
        pool=pool,
        identity_name="alpha_mx",
        backfill=True,
        backfill_limit=10,
    )
    await coll.on_subscribe()
    fake = coll._client
    assert isinstance(fake, _FakeAsyncClient)

    # Set up the fake nio surface for backfill.
    room_id = "!room:example.org"
    fake_room = _FakeRoom(room_id=room_id)
    fake.rooms[room_id] = fake_room
    # The sync response carries `rooms.join[room_id].timeline.prev_batch`.
    timeline = Timeline(events=[], limited=False, prev_batch="page0")
    room_info = RoomInfo(
        timeline=timeline,
        state=[],
        ephemeral=[],
        account_data=[],
        summary=None,
        unread_notifications=None,
    )
    rooms = Rooms(invite={}, join={room_id: room_info}, leave={})
    fake._sync_response = SyncResponse(  # type: ignore[attr-defined]
        next_batch="batch1",
        rooms=rooms,
        device_key_count={},
        device_list=None,
        to_device_events=[],
        presence_events=[],
        account_data_events=[],
    )
    # Two pages of history, then exhausted (end=None).
    events_page1 = [
        _build_text_event("$h1", "@bob:example.org", 1_716_000_000_000, "history msg 1"),
        _build_text_event("$h2", "@bob:example.org", 1_716_000_001_000, "history msg 2"),
    ]
    events_page2 = [
        _build_text_event("$h3", "@carol:example.org", 1_716_000_002_000, "history msg 3"),
    ]
    fake._messages_pages = [  # type: ignore[attr-defined]
        RoomMessagesResponse(room_id=room_id, chunk=events_page1, start="page0", end="page1"),
        RoomMessagesResponse(room_id=room_id, chunk=events_page2, start="page1", end=None),
    ]

    # Drive the backfill task to completion.
    assert coll._backfill_task is not None
    await coll._backfill_task

    # 3 historical text events ingested + published.
    assert len(captured) == 3
    assert all(s == f"raw.message.matrix.{coll.instance_id}" for s in captured)

    await coll.shutdown()
    await storage.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_self_echo_dropped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(matrix_real, "AsyncClient", _FakeAsyncClient)
    cfg_path = _setup_pool(tmp_path, "alpha_mx")
    pool = FileIdentityPool(cfg_path)
    bus = MemoryBus()
    storage = SQLiteStorage(tmp_path / "data")
    captured: list[str] = []

    async def _recorder(subject: str, _p: bytes, _h: dict[str, str]) -> None:
        captured.append(subject)

    await bus.subscribe("raw.message.>", _recorder)

    coll = MatrixCollector(bus=bus, storage=storage, pool=pool, identity_name="alpha_mx")
    await coll.on_subscribe()
    room = _FakeRoom(room_id="!room:example.org")
    # Sender == our own user_id → drop. The identity's user_id is
    # "@alpha_mx:example.org" per _setup_pool.
    own_user = "@alpha_mx:example.org"
    event = _FakeTextEvent(event_id="$echo", sender=own_user, server_timestamp=1, body="my own msg")
    await coll._on_message(room, event)
    await asyncio.sleep(0)
    assert captured == []

    await coll.shutdown()
    await storage.close()
