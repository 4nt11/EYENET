"""Unit tests for the Engine — debounce, candidate vs current, recipe wiring."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from eyenet.bus import MemoryBus
from eyenet.contracts.attribution import (
    SUBJECT_PROFILE_CANDIDATE,
    SUBJECT_PROFILE_CURRENT,
    ProfileCandidateEnvelope,
    ProfileCurrentEnvelope,
)
from eyenet.contracts.enums import ValueKind
from eyenet.contracts.observation import ObservationRow
from eyenet.engine.engine import Engine
from eyenet.storage import SQLiteStorage

_TS = datetime(2026, 5, 1, tzinfo=UTC)
_TRACEPARENT = "00-" + "a" * 32 + "-" + "b" * 16 + "-01"
_ACTOR_UUID = UUID("00000000-0000-0000-0000-000000000001")


def _obs_row(
    actor_id: UUID,
    primitive: str,
    value_numeric: float | None = None,
    value_hash: str | None = None,
    value_enum: str | None = None,
) -> ObservationRow:
    from eyenet.contracts._base import _new_uuid7

    vkind = (
        ValueKind.NUMERIC
        if value_numeric is not None
        else ValueKind.HASH
        if value_hash is not None
        else ValueKind.ENUM_STR
    )
    return ObservationRow(
        id=_new_uuid7(),
        actor_id=actor_id,
        primitive_namespace=primitive.split(".", maxsplit=1)[0],
        primitive_name=primitive,
        primitive_version="0.1",
        value_kind=vkind,
        value_numeric=value_numeric,
        value_hash=value_hash,
        value_enum=value_enum,
        evidence_ref="test:ref:1",
        observed_at=_TS,
        sensor_instance="test",
    )


def _fake_observation_payload(primitive: str, evidence_ref: str) -> bytes:
    """Minimal BEHAVE-TEXT Observation JSON payload."""
    return json.dumps(
        {
            "primitive": primitive,
            "value": 0.5,
            "confidence": 0.8,
            "window": {"start_ts": 1_000_000.0, "end_ts": 1_001_000.0},
            "source": "test",
            "evidence_ref": evidence_ref,
            "ts": 1_000_000.0,
            "v": "1.0",
        }
    ).encode()


@pytest.fixture
def tmp_storage(tmp_path: Path) -> SQLiteStorage:
    return SQLiteStorage(tmp_path)


@pytest.fixture
def bus() -> MemoryBus:
    return MemoryBus()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_candidate_emits_on_slot_update(tmp_storage: SQLiteStorage, bus: MemoryBus) -> None:
    received_candidates: list[ProfileCandidateEnvelope] = []

    async def _sniff(subject: str, payload: bytes, headers: dict[str, str]) -> None:
        if subject == SUBJECT_PROFILE_CANDIDATE:
            received_candidates.append(ProfileCandidateEnvelope.model_validate_json(payload))

    await bus.subscribe(SUBJECT_PROFILE_CANDIDATE, _sniff)
    await bus.subscribe(SUBJECT_PROFILE_CURRENT, _sniff)

    engine = Engine(bus=bus, storage=tmp_storage)
    await engine.on_subscribe()

    evidence_ref = "test:ref:emit:1"
    primitive = "lexical.vocabulary_richness"
    row = _obs_row(_ACTOR_UUID, primitive, value_numeric=0.72)
    row = row.model_copy(update={"evidence_ref": evidence_ref})
    await tmp_storage.observations.put(row)

    payload = _fake_observation_payload(primitive, evidence_ref)
    headers = {"traceparent": _TRACEPARENT}
    await bus.publish("actor.observation.text.lexical", payload, headers=headers)

    # Give the async task time to process
    await asyncio.sleep(0.2)

    assert len(received_candidates) >= 1
    candidate = received_candidates[0]
    assert candidate.actor_id == _ACTOR_UUID


@pytest.mark.unit
@pytest.mark.asyncio
async def test_current_suppressed_on_duplicate_value(
    tmp_storage: SQLiteStorage, bus: MemoryBus
) -> None:
    """Second observation with same slot value should NOT emit a new ProfileCurrent."""
    received_currents: list[ProfileCurrentEnvelope] = []

    async def _sniff_current(subject: str, payload: bytes, headers: dict[str, str]) -> None:
        if subject == SUBJECT_PROFILE_CURRENT:
            received_currents.append(ProfileCurrentEnvelope.model_validate_json(payload))

    await bus.subscribe(SUBJECT_PROFILE_CURRENT, _sniff_current)

    engine = Engine(bus=bus, storage=tmp_storage)
    await engine.on_subscribe()

    primitive = "lexical.vocabulary_richness"
    evidence_ref_1 = "test:ref:dup:1"
    evidence_ref_2 = "test:ref:dup:2"

    row1 = _obs_row(_ACTOR_UUID, primitive, value_numeric=0.72)
    row1 = row1.model_copy(update={"evidence_ref": evidence_ref_1})
    await tmp_storage.observations.put(row1)

    row2 = _obs_row(_ACTOR_UUID, primitive, value_numeric=0.72)  # same value
    row2 = row2.model_copy(update={"evidence_ref": evidence_ref_2})
    await tmp_storage.observations.put(row2)

    headers = {"traceparent": _TRACEPARENT}

    # First observation → should emit current
    await bus.publish(
        "actor.observation.text.lexical",
        _fake_observation_payload(primitive, evidence_ref_1),
        headers=headers,
    )
    await asyncio.sleep(0.2)
    first_count = len(received_currents)

    # Second observation with same value → should NOT emit current
    await bus.publish(
        "actor.observation.text.lexical",
        _fake_observation_payload(primitive, evidence_ref_2),
        headers=headers,
    )
    await asyncio.sleep(0.2)

    assert first_count >= 1, "First observation should emit current"
    assert len(received_currents) == first_count, "Duplicate value should not emit new current"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_current_emits_on_changed_value(tmp_storage: SQLiteStorage, bus: MemoryBus) -> None:
    """Different slot value should emit a new ProfileCurrent."""
    received_currents: list[ProfileCurrentEnvelope] = []

    async def _sniff_current(subject: str, payload: bytes, headers: dict[str, str]) -> None:
        if subject == SUBJECT_PROFILE_CURRENT:
            received_currents.append(ProfileCurrentEnvelope.model_validate_json(payload))

    await bus.subscribe(SUBJECT_PROFILE_CURRENT, _sniff_current)

    engine = Engine(bus=bus, storage=tmp_storage)
    await engine.on_subscribe()

    primitive = "lexical.vocabulary_richness"
    evidence_ref_1 = "test:ref:change:1"
    evidence_ref_2 = "test:ref:change:2"

    row1 = _obs_row(_ACTOR_UUID, primitive, value_numeric=0.72)
    row1 = row1.model_copy(update={"evidence_ref": evidence_ref_1})
    await tmp_storage.observations.put(row1)

    row2 = _obs_row(_ACTOR_UUID, primitive, value_numeric=0.55)  # different value
    row2 = row2.model_copy(update={"evidence_ref": evidence_ref_2})
    await tmp_storage.observations.put(row2)

    headers = {"traceparent": _TRACEPARENT}

    await bus.publish(
        "actor.observation.text.lexical",
        _fake_observation_payload(primitive, evidence_ref_1),
        headers=headers,
    )
    await asyncio.sleep(0.2)
    first_count = len(received_currents)

    await bus.publish(
        "actor.observation.text.lexical",
        _fake_observation_payload(primitive, evidence_ref_2),
        headers=headers,
    )
    await asyncio.sleep(0.2)

    assert len(received_currents) > first_count, "Changed value should emit a new ProfileCurrent"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_unknown_primitive_does_not_emit(tmp_storage: SQLiteStorage, bus: MemoryBus) -> None:
    received: list[bytes] = []

    async def _sniff(_s: str, payload: bytes, _h: dict[str, str]) -> None:
        received.append(payload)

    await bus.subscribe(SUBJECT_PROFILE_CANDIDATE, _sniff)
    await bus.subscribe(SUBJECT_PROFILE_CURRENT, _sniff)

    engine = Engine(bus=bus, storage=tmp_storage)
    await engine.on_subscribe()

    primitive = "unknown.future_primitive"
    evidence_ref = "test:ref:unknown:1"
    row = _obs_row(_ACTOR_UUID, primitive, value_numeric=0.5)
    row = row.model_copy(update={"evidence_ref": evidence_ref})
    await tmp_storage.observations.put(row)

    await bus.publish(
        "actor.observation.text.unknown",
        _fake_observation_payload(primitive, evidence_ref),
        headers={"traceparent": _TRACEPARENT},
    )
    await asyncio.sleep(0.2)

    assert len(received) == 0
