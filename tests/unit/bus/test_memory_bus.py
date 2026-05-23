"""MemoryBus contract: round-trip, queue groups, wildcards, request/reply."""

from __future__ import annotations

import asyncio

import pytest

from eyenet.bus.memory import MemoryBus


@pytest.mark.unit
@pytest.mark.asyncio
async def test_publish_subscribe_roundtrip() -> None:
    bus = MemoryBus()
    received: list[tuple[str, bytes, dict[str, str]]] = []

    async def handler(subject: str, payload: bytes, headers: dict[str, str]) -> None:
        received.append((subject, payload, headers))

    await bus.subscribe("a.b.c", handler)
    await bus.publish("a.b.c", b"hello", headers={"x": "y"})
    await asyncio.sleep(0)
    assert received == [("a.b.c", b"hello", {"x": "y"})]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_wildcard_subscribe() -> None:
    bus = MemoryBus()
    received: list[str] = []

    async def handler(subject: str, _payload: bytes, _headers: dict[str, str]) -> None:
        received.append(subject)

    await bus.subscribe("raw.message.>", handler)
    await bus.publish("raw.message.telegram.abcd1234", b"")
    await bus.publish("raw.message.matrix.deadbeef", b"")
    await bus.publish("actor.observation.text.x", b"")  # not matched
    await asyncio.sleep(0)
    assert sorted(received) == [
        "raw.message.matrix.deadbeef",
        "raw.message.telegram.abcd1234",
    ]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_queue_group_round_robin() -> None:
    bus = MemoryBus()
    a_count = 0
    b_count = 0

    async def handler_a(*_: object) -> None:
        nonlocal a_count
        a_count += 1

    async def handler_b(*_: object) -> None:
        nonlocal b_count
        b_count += 1

    await bus.subscribe("raw.message.>", handler_a, queue_group="sensor")
    await bus.subscribe("raw.message.>", handler_b, queue_group="sensor")

    for _ in range(10):
        await bus.publish("raw.message.telegram.x", b"")
    await asyncio.sleep(0)
    assert a_count + b_count == 10
    # Round-robin should split exactly 5/5 with our deterministic cycle.
    assert a_count == 5
    assert b_count == 5


@pytest.mark.unit
@pytest.mark.asyncio
async def test_broadcast_outside_queue_group() -> None:
    bus = MemoryBus()
    seen: list[str] = []

    async def h1(*_: object) -> None:
        seen.append("h1")

    async def h2(*_: object) -> None:
        seen.append("h2")

    await bus.subscribe("a", h1)
    await bus.subscribe("a", h2)
    await bus.publish("a", b"")
    await asyncio.sleep(0)
    assert sorted(seen) == ["h1", "h2"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_unsubscribe_stops_delivery() -> None:
    bus = MemoryBus()
    seen: list[bytes] = []

    async def h(_s: str, p: bytes, _h: dict[str, str]) -> None:
        seen.append(p)

    sub = await bus.subscribe("a", h)
    await bus.publish("a", b"1")
    await sub.unsubscribe()
    await bus.publish("a", b"2")
    await asyncio.sleep(0)
    assert seen == [b"1"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_failing_handler_does_not_block_siblings() -> None:
    bus = MemoryBus()
    seen: list[str] = []

    async def bad(*_: object) -> None:
        raise RuntimeError("boom")

    async def good(*_: object) -> None:
        seen.append("good")

    await bus.subscribe("a", bad)
    await bus.subscribe("a", good)
    await bus.publish("a", b"")
    await asyncio.sleep(0)
    assert seen == ["good"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_request_reply() -> None:
    bus = MemoryBus()

    async def responder(subject: str, payload: bytes, headers: dict[str, str]) -> None:
        reply_to = headers["__reply_to__"]
        await bus.publish(reply_to, b"pong:" + payload)

    await bus.subscribe("ping", responder)
    body, _hdrs = await bus.request("ping", b"hi", timeout=1.0)
    assert body == b"pong:hi"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_close_refuses_publish() -> None:
    bus = MemoryBus()
    await bus.close()
    with pytest.raises(RuntimeError):
        await bus.publish("a", b"")
