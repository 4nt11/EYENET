"""M8: relation graph — replies, edits, reactions."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from sqlmodel import Session, select

from eyenet.bus import MemoryBus
from eyenet.collectors.matrix import real as matrix_real
from eyenet.collectors.matrix.real import MatrixCollector
from eyenet.contracts.enums import SourceKind
from eyenet.contracts.raw_message import RawMessageEnvelope
from eyenet.identity_pool import FileIdentityPool, IdentityFile, IdentityFileEntry
from eyenet.identity_pool.loader import dump
from eyenet.models import MessageTable, ReactionTable
from eyenet.storage import SQLiteStorage
from eyenet.storage.engines import StoreName

from .test_matrix_collector_unit import _FakeAsyncClient, _FakeRoom


@dataclass
class _FakeRichEvent:
    """Fake event with a `source` dict carrying full Matrix content."""

    event_id: str
    sender: str
    server_timestamp: int
    body: str
    source: dict[str, Any] = field(default_factory=dict)


@dataclass
class _FakeReactionEvent:
    event_id: str
    sender: str
    server_timestamp: int
    source: dict[str, Any] = field(default_factory=dict)


async def _setup_collector(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[MatrixCollector, MemoryBus, SQLiteStorage, list[bytes]]:
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
    storage = SQLiteStorage(tmp_path / "data")
    captured: list[bytes] = []

    async def _recorder(_subject: str, payload: bytes, _h: dict[str, str]) -> None:
        captured.append(payload)

    await bus.subscribe("raw.message.>", _recorder)
    coll = MatrixCollector(bus=bus, storage=storage, pool=pool, identity_name="alpha_mx")
    return coll, bus, storage, captured


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reply_to_platform_msgid_published(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    coll, _bus, storage, captured = await _setup_collector(tmp_path, monkeypatch)
    await coll.on_subscribe()
    room = _FakeRoom(room_id="!room:example.org")

    parent = _FakeRichEvent(
        event_id="$parent",
        sender="@bob:example.org",
        server_timestamp=1_716_000_000_000,
        body="hello parent",
        source={"content": {"msgtype": "m.text", "body": "hello parent"}},
    )
    child = _FakeRichEvent(
        event_id="$child",
        sender="@carol:example.org",
        server_timestamp=1_716_000_001_000,
        body="reply text",
        source={
            "content": {
                "msgtype": "m.text",
                "body": "reply text",
                "m.relates_to": {"m.in_reply_to": {"event_id": "$parent"}},
            }
        },
    )
    await coll._on_message(room, parent)
    await coll._on_message(room, child)
    await asyncio.sleep(0)

    envs = [RawMessageEnvelope.model_validate_json(p) for p in captured]
    parent_env = next(e for e in envs if e.platform_msgid == "$parent")
    child_env = next(e for e in envs if e.platform_msgid == "$child")
    assert parent_env.reply_to_platform_msgid is None
    assert child_env.reply_to_platform_msgid == "$parent"

    # FK resolved on insert because parent landed first.
    engine = storage._engines[StoreName.MAIN]
    with Session(engine) as s:
        rows = s.exec(select(MessageTable).order_by(MessageTable.platform_msgid)).all()
        by_id = {r.platform_msgid: r for r in rows}
        assert by_id["$child"].reply_to_msg_id == by_id["$parent"].id

    await coll.shutdown()
    await storage.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reply_pending_when_parent_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Out-of-order: child arrives before parent → FK None, platform id stashed."""
    coll, _bus, storage, _captured = await _setup_collector(tmp_path, monkeypatch)
    await coll.on_subscribe()
    room = _FakeRoom(room_id="!room:example.org")

    child = _FakeRichEvent(
        event_id="$child",
        sender="@carol:example.org",
        server_timestamp=1_716_000_001_000,
        body="dangling reply",
        source={
            "content": {
                "msgtype": "m.text",
                "body": "dangling reply",
                "m.relates_to": {"m.in_reply_to": {"event_id": "$missing"}},
            }
        },
    )
    await coll._on_message(room, child)

    engine = storage._engines[StoreName.MAIN]
    with Session(engine) as s:
        row = s.exec(select(MessageTable).where(MessageTable.platform_msgid == "$child")).first()
        assert row is not None
        assert row.reply_to_msg_id is None
        assert row.source_specific.get("pending_reply_to") == "$missing"

    await coll.shutdown()
    await storage.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_edit_replaces_body_and_keeps_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    coll, _bus, storage, _captured = await _setup_collector(tmp_path, monkeypatch)
    await coll.on_subscribe()
    room = _FakeRoom(room_id="!room:example.org")

    original = _FakeRichEvent(
        event_id="$orig",
        sender="@bob:example.org",
        server_timestamp=1_716_000_000_000,
        body="first draft",
        source={"content": {"msgtype": "m.text", "body": "first draft"}},
    )
    edit = _FakeRichEvent(
        event_id="$edit1",
        sender="@bob:example.org",
        server_timestamp=1_716_000_500_000,
        body="* second draft",
        source={
            "content": {
                "msgtype": "m.text",
                "body": "* second draft",
                "m.new_content": {"msgtype": "m.text", "body": "second draft"},
                "m.relates_to": {"rel_type": "m.replace", "event_id": "$orig"},
            }
        },
    )
    await coll._on_message(room, original)
    await coll._on_message(room, edit)

    engine = storage._engines[StoreName.MAIN]
    with Session(engine) as s:
        row = s.exec(select(MessageTable).where(MessageTable.platform_msgid == "$orig")).first()
        assert row is not None
        assert row.body == "second draft"
        edits = row.source_specific.get("edits") or []
        assert len(edits) == 2
        assert edits[0]["body"] == "first draft"
        assert edits[1]["body"] == "second draft"
        assert edits[1]["event_id"] == "$edit1"

    await coll.shutdown()
    await storage.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reaction_inserted_into_reaction_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    coll, _bus, storage, _captured = await _setup_collector(tmp_path, monkeypatch)
    await coll.on_subscribe()
    room = _FakeRoom(room_id="!room:example.org")

    msg = _FakeRichEvent(
        event_id="$target",
        sender="@bob:example.org",
        server_timestamp=1_716_000_000_000,
        body="react to me",
        source={"content": {"msgtype": "m.text", "body": "react to me"}},
    )
    await coll._on_message(room, msg)

    reaction = _FakeReactionEvent(
        event_id="$rxn1",
        sender="@carol:example.org",
        server_timestamp=1_716_000_001_000,
        source={
            "content": {
                "m.relates_to": {
                    "rel_type": "m.annotation",
                    "event_id": "$target",
                    "key": "👍",
                }
            }
        },
    )
    await coll._on_reaction(room, reaction)

    engine = storage._engines[StoreName.MAIN]
    with Session(engine) as s:
        rows = s.exec(select(ReactionTable)).all()
        assert len(rows) == 1
        assert rows[0].emoji == "👍"
        assert rows[0].evidence_ref == "matrix:!room:example.org:$rxn1"

    await coll.shutdown()
    await storage.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_badevent_counted_and_logged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """nio's BadEvent / UnknownBadEvent must be observed, not invisibly dropped."""
    from nio.events.misc import BadEvent, UnknownBadEvent

    coll, _bus, storage, _captured = await _setup_collector(tmp_path, monkeypatch)
    await coll.on_subscribe()
    room = _FakeRoom(room_id="!room:example.org")

    bad = BadEvent(
        source={"type": "m.room.create"},
        event_id="$bad1",
        sender="@bob:example.org",
        server_timestamp=1_716_000_000_000,
        type="m.room.create",
    )
    unknown = UnknownBadEvent(source={"missing": "everything"})

    await coll._on_badevent(room, bad)
    await coll._on_badevent(room, unknown)

    assert coll._badevent_count == 2
    assert coll._badevent_by_type["m.room.create"] == 1
    assert coll._badevent_by_type["<unknown>"] == 1

    await coll.shutdown()
    await storage.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reaction_dropped_when_target_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    coll, _bus, storage, _captured = await _setup_collector(tmp_path, monkeypatch)
    await coll.on_subscribe()
    room = _FakeRoom(room_id="!room:example.org")

    reaction = _FakeReactionEvent(
        event_id="$orphan",
        sender="@carol:example.org",
        server_timestamp=1_716_000_001_000,
        source={
            "content": {
                "m.relates_to": {
                    "rel_type": "m.annotation",
                    "event_id": "$nobody",
                    "key": "🔥",
                }
            }
        },
    )
    await coll._on_reaction(room, reaction)

    engine = storage._engines[StoreName.MAIN]
    with Session(engine) as s:
        rows = s.exec(select(ReactionTable)).all()
        assert rows == []

    await coll.shutdown()
    await storage.close()
