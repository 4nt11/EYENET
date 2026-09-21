"""BusEnvelopePublisher refuses publish without trace_context / on unknown subject."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from eyenet.bus.memory import MemoryBus
from eyenet.bus.publisher import BusEnvelopePublisher
from eyenet.contracts._base import TraceContext
from eyenet.contracts.attribution import ProfileCandidateEnvelope

TC = TraceContext(traceparent="00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01")
NOW = datetime(2026, 5, 4, tzinfo=UTC)
A = UUID("00000000-0000-0000-0000-000000000001")


def _envelope() -> ProfileCandidateEnvelope:
    return ProfileCandidateEnvelope(
        profile_id=A,
        actor_id=A,
        version=1,
        role_confidence=0.0,
        derived_at=NOW,
        derived_from_observation_count=0,
        trace_context=TC,
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_publishes_to_known_subject_with_headers() -> None:
    bus = MemoryBus()
    received_headers: list[dict[str, str]] = []

    async def handler(_s: str, _p: bytes, h: dict[str, str]) -> None:
        received_headers.append(h)

    await bus.subscribe("attribution.profile.candidate", handler)
    pub = BusEnvelopePublisher(bus)
    await pub.publish("attribution.profile.candidate", _envelope())
    import asyncio

    await asyncio.sleep(0)
    assert received_headers
    assert received_headers[0]["traceparent"] == TC.traceparent
    assert received_headers[0]["schema-version"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_refuses_unknown_subject() -> None:
    bus = MemoryBus()
    pub = BusEnvelopePublisher(bus)
    with pytest.raises(ValueError, match="unknown subject"):
        await pub.publish("totally.made.up", _envelope())


@pytest.mark.unit
@pytest.mark.asyncio
async def test_renders_raw_message_subject() -> None:
    bus = MemoryBus()
    pub = BusEnvelopePublisher(bus)
    # Subject with rendered placeholders is allowed.
    seen: list[str] = []

    async def h(s: str, _p: bytes, _h: dict[str, str]) -> None:
        seen.append(s)

    await bus.subscribe("raw.message.>", h)
    from eyenet.contracts.enums import SourceKind
    from eyenet.contracts.raw_message import RawMessageEnvelope

    env = RawMessageEnvelope(
        source=SourceKind.TELEGRAM,
        instance_id="abcd1234",
        evidence_ref="telegram:-100:42",
        actor_key="actor:" + "a" * 64,
        platform_groupid="-100",
        platform_msgid="42",
        sent_at_source=NOW,
        collected_at=NOW,
        length_chars=10,
        length_words=2,
        body_sha256="b" * 64,
        trace_context=TC,
    )
    await pub.publish("raw.message.telegram.abcd1234", env)
    import asyncio

    await asyncio.sleep(0)
    assert seen == ["raw.message.telegram.abcd1234"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stamps_event_id_header_when_given() -> None:
    # The durable event_id rides as a header so the SSE stream can dedup a live
    # event against the same event replayed from the event log (M9.H2).
    bus = MemoryBus()
    headers: list[dict[str, str]] = []

    async def handler(_s: str, _p: bytes, h: dict[str, str]) -> None:
        headers.append(h)

    await bus.subscribe("attribution.profile.candidate", handler)
    pub = BusEnvelopePublisher(bus)
    eid = UUID("06ab1493-2552-7a7a-8000-1bc7b549e8dd")
    await pub.publish("attribution.profile.candidate", _envelope(), event_id=eid)
    import asyncio

    await asyncio.sleep(0)
    assert headers and headers[0]["eyenet-event-id"] == str(eid)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_no_event_id_header_by_default() -> None:
    bus = MemoryBus()
    headers: list[dict[str, str]] = []

    async def handler(_s: str, _p: bytes, h: dict[str, str]) -> None:
        headers.append(h)

    await bus.subscribe("attribution.profile.candidate", handler)
    pub = BusEnvelopePublisher(bus)
    await pub.publish("attribution.profile.candidate", _envelope())
    import asyncio

    await asyncio.sleep(0)
    assert headers and "eyenet-event-id" not in headers[0]


@pytest.mark.unit
def test_bus_property_exposes_wrapped_bus() -> None:
    bus = MemoryBus()
    assert BusEnvelopePublisher(bus).bus is bus
