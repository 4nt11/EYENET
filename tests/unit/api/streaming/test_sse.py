# SPDX-License-Identifier: AGPL-3.0-or-later
"""SSE generator, frame formatting, and topic authorization (M9.H2/H3/H5).

The generator yields exactly one frame per ``__anext__``, which makes the
replay→live and backpressure sequences deterministic to drive.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from uuid_extensions import uuid7

import eyenet.api.streaming.sse as ssemod
from eyenet.api.deps import AuthError, StreamPrincipal
from eyenet.api.streaming.sse import (
    _event_name,
    _frame,
    _lag_ms,
    _parse_cursor,
    _replay_data,
    require_topic,
    require_topic_set,
    sse_stream,
)
from eyenet.bus.memory import MemoryBus
from eyenet.contracts.enums import SystemUserRole
from eyenet.contracts.event_log import EventLogRow
from eyenet.storage.repository import BaseRepository

from .conftest import FakeRequest

pytestmark = pytest.mark.unit

_TP = "00-" + "0" * 32 + "-" + "0" * 16 + "-01"


def _uid() -> UUID:
    return UUID(str(uuid7()))


async def _anext(ait: object, timeout_s: float = 2.0) -> bytes:
    return await asyncio.wait_for(ait.__anext__(), timeout_s)  # type: ignore[attr-defined]


# --- pure helpers -----------------------------------------------------------
def test_frame_data_and_id() -> None:
    out = _frame(event="linkage.confirmed", data='{"x":1}', event_id="abc").decode()
    assert out == 'id: abc\nevent: linkage.confirmed\ndata: {"x":1}\n\n'


def test_frame_without_id_omits_id_line() -> None:
    out = _frame(event="linkage.proposed", data="{}").decode()
    assert "id:" not in out
    assert out.startswith("event: linkage.proposed\n")


def test_frame_comment_is_heartbeat() -> None:
    assert _frame(comment="heartbeat") == b": heartbeat\n\n"


def test_frame_multiline_data_prefixes_each_line() -> None:
    out = _frame(data="a\nb").decode()
    assert "data: a\ndata: b\n\n" in out


@pytest.mark.parametrize(
    ("subject", "expected"),
    [
        ("attribution.linkage.confirmed", "linkage.confirmed"),
        ("eyenet.identity.released", "identity.released"),
        ("eyenet.control.panic", "control.panic"),
    ],
)
def test_event_name_drops_namespace(subject: str, expected: str) -> None:
    assert _event_name(subject) == expected


def test_lag_ms_valid_emitted_at() -> None:
    import json

    payload = json.dumps({"emitted_at": datetime.now(tz=UTC).isoformat()}).encode()
    lag = _lag_ms(payload)
    assert lag is not None and lag >= 0


def test_lag_ms_handles_bad_payloads() -> None:
    assert _lag_ms(b"not json at all") is None
    assert _lag_ms(b'{"emitted_at": 123}') is None  # not a string


def test_parse_cursor_bad_uuid_returns_none() -> None:
    assert _parse_cursor("not-a-uuid") is None


def test_replay_data_is_metadata_with_flag() -> None:
    row = EventLogRow(
        parent_id=_uid(),
        event_seq=1,
        event_subject="attribution.linkage.confirmed",
        event_id=_uid(),
        ts=datetime.now(tz=UTC),
        traceparent=_TP,
        tracestate=None,
        actor="op",
        payload_digest="deadbeef",
    )
    import json

    data = json.loads(_replay_data(row))
    assert data["_replay"] is True
    assert data["payload_digest"] == "deadbeef"
    assert "payload" not in data  # metadata only — bodies are not in the event log


# --- authorization ----------------------------------------------------------
def _principal(topics: set[str]) -> StreamPrincipal:
    return StreamPrincipal(
        user_id=_uid(),
        username="op",
        role=SystemUserRole.ADMIN,
        topics=frozenset(topics),
        expires_at=datetime.now(tz=UTC) + timedelta(minutes=10),
    )


def test_require_topic_passes_and_rejects() -> None:
    p = _principal({"attribution.linkage"})
    require_topic(p, "attribution.linkage")  # no raise
    with pytest.raises(AuthError):
        require_topic(p, "eyenet.audit")


def test_require_topic_set_equality() -> None:
    p = _principal({"attribution.linkage", "eyenet.audit"})
    require_topic_set(p, ["attribution.linkage", "eyenet.audit"])  # equal → ok
    with pytest.raises(AuthError):
        require_topic_set(p, ["attribution.linkage"])  # subset → mismatch
    with pytest.raises(AuthError):
        require_topic_set(p, ["attribution.linkage", "eyenet.audit", "eyenet.control"])


# --- live delivery ----------------------------------------------------------
async def test_live_event_delivered_with_id_and_name(
    fake_request: FakeRequest, bus: MemoryBus, storage: BaseRepository
) -> None:
    p = _principal({"attribution.linkage"})
    gen = sse_stream(
        request=fake_request,
        bus=bus,
        storage=storage,
        principal=p,
        topics=["attribution.linkage"],
        last_event_id=None,
    )
    ait = gen.__aiter__()
    task = asyncio.create_task(_anext(ait))
    await asyncio.sleep(0.05)  # subscribe + block on queue.get
    eid = str(_uid())
    await bus.publish("attribution.linkage.confirmed", b'{"a":1}', headers={"eyenet-event-id": eid})
    frame = (await task).decode()
    assert f"id: {eid}" in frame
    assert "event: linkage.confirmed" in frame
    assert 'data: {"a":1}' in frame
    await gen.aclose()


async def test_live_event_without_durable_id_has_no_id_line(
    fake_request: FakeRequest, bus: MemoryBus, storage: BaseRepository
) -> None:
    p = _principal({"attribution.linkage"})
    gen = sse_stream(
        request=fake_request,
        bus=bus,
        storage=storage,
        principal=p,
        topics=["attribution.linkage"],
        last_event_id=None,
    )
    ait = gen.__aiter__()
    task = asyncio.create_task(_anext(ait))
    await asyncio.sleep(0.05)
    # A sister-service emission (no eyenet-event-id header) — live-only.
    await bus.publish("attribution.linkage.proposed", b"{}", headers={})
    frame = (await task).decode()
    assert "id:" not in frame
    assert "event: linkage.proposed" in frame
    await gen.aclose()


# --- reconnect: replay then exact-once dedup at the boundary (H2 DoD) --------
async def test_reconnect_replays_then_dedups_boundary(
    fake_request: FakeRequest, bus: MemoryBus, storage: BaseRepository
) -> None:
    cursor = _uid()  # client's Last-Event-ID
    e0 = _uid()  # a durable event the client missed (event_id > cursor)
    await storage.append_linkage_event(
        linkage_id=_uid(),
        event_subject="attribution.linkage.confirmed",
        event_id=e0,
        traceparent=_TP,
    )
    p = _principal({"attribution.linkage"})
    gen = sse_stream(
        request=fake_request,
        bus=bus,
        storage=storage,
        principal=p,
        topics=["attribution.linkage"],
        last_event_id=str(cursor),
    )
    ait = gen.__aiter__()

    # 1) replay delivers the missed durable event exactly once.
    replay_frame = (await _anext(ait)).decode()
    assert f"id: {e0}" in replay_frame
    assert '"_replay": true' in replay_frame

    # 2) live-tail: the SAME event replayed onto the bus is deduped; a NEW one flows.
    task = asyncio.create_task(_anext(ait))
    await asyncio.sleep(0.05)  # generator enters live loop, blocks on get
    await bus.publish(
        "attribution.linkage.confirmed", b'{"dup":1}', headers={"eyenet-event-id": str(e0)}
    )
    e1 = str(_uid())
    await bus.publish(
        "attribution.linkage.confirmed", b'{"new":1}', headers={"eyenet-event-id": e1}
    )
    frame = (await task).decode()
    assert f"id: {e1}" in frame  # the dup (e0) was skipped
    assert '{"new":1}' in frame
    await gen.aclose()


# --- heartbeat --------------------------------------------------------------
async def test_heartbeat_on_idle(
    monkeypatch: pytest.MonkeyPatch,
    fake_request: FakeRequest,
    bus: MemoryBus,
    storage: BaseRepository,
) -> None:
    monkeypatch.setattr(ssemod, "HEARTBEAT_SECONDS", 0.05)
    p = _principal({"attribution.linkage"})
    gen = sse_stream(
        request=fake_request,
        bus=bus,
        storage=storage,
        principal=p,
        topics=["attribution.linkage"],
        last_event_id=None,
    )
    ait = gen.__aiter__()
    frame = await _anext(ait)
    assert frame == b": heartbeat\n\n"
    await gen.aclose()


# --- backpressure (H3 DoD) --------------------------------------------------
async def test_backpressure_trips_and_closes(
    monkeypatch: pytest.MonkeyPatch,
    fake_request: FakeRequest,
    bus: MemoryBus,
    storage: BaseRepository,
) -> None:
    monkeypatch.setattr(ssemod, "HWM", 1)
    p = _principal({"attribution.linkage"})
    gen = sse_stream(
        request=fake_request,
        bus=bus,
        storage=storage,
        principal=p,
        topics=["attribution.linkage"],
        last_event_id=None,
    )
    ait = gen.__aiter__()
    task = asyncio.create_task(_anext(ait))
    await asyncio.sleep(0.05)
    # First event is delivered to the waiting consumer.
    await bus.publish(
        "attribution.linkage.confirmed", b'{"n":1}', headers={"eyenet-event-id": str(_uid())}
    )
    first = (await task).decode()
    assert "event: linkage.confirmed" in first
    # Generator now suspended at the yield. Two more with HWM=1: one queues, one
    # overflows → overflow flag set, none delivered.
    await bus.publish(
        "attribution.linkage.confirmed", b'{"n":2}', headers={"eyenet-event-id": str(_uid())}
    )
    await bus.publish(
        "attribution.linkage.confirmed", b'{"n":3}', headers={"eyenet-event-id": str(_uid())}
    )
    assert (await _anext(ait)).decode().startswith("event: stream.backpressure")
    assert (await _anext(ait)).decode().startswith("event: stream.expired")
    with pytest.raises(StopAsyncIteration):
        await _anext(ait)


# --- token expiry mid-stream ------------------------------------------------
async def test_token_expiry_closes_with_expired(
    fake_request: FakeRequest, bus: MemoryBus, storage: BaseRepository
) -> None:
    expired = StreamPrincipal(
        user_id=_uid(),
        username="op",
        role=SystemUserRole.ADMIN,
        topics=frozenset({"attribution.linkage"}),
        expires_at=datetime.now(tz=UTC) - timedelta(seconds=1),
    )
    gen = sse_stream(
        request=fake_request,
        bus=bus,
        storage=storage,
        principal=expired,
        topics=["attribution.linkage"],
        last_event_id=None,
    )
    ait = gen.__aiter__()
    frame = (await _anext(ait)).decode()
    assert frame.startswith("event: stream.expired")
    assert "token_expired" in frame
    with pytest.raises(StopAsyncIteration):
        await _anext(ait)
