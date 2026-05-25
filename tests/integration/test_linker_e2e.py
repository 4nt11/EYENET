"""Integration test: Engine + Linker over MemoryBus.

Two actors with deliberately-close simhashes → LinkageProposed lands.
One pair beyond threshold → no proposal.
"""

from __future__ import annotations

import asyncio
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest

from eyenet.bus import MemoryBus
from eyenet.contracts._base import TraceContext, _new_uuid7
from eyenet.contracts.attribution import (
    SUBJECT_LINKAGE_PROPOSED,
    SUBJECT_PROFILE_CURRENT,
    LinkageProposedEnvelope,
    LinkageRow,
    ProfileCurrentEnvelope,
)
from eyenet.linker.linker import Linker
from eyenet.storage import SQLiteStorage

_TC = TraceContext(traceparent="00-" + "a" * 32 + "-" + "b" * 16 + "-01")
_NOW = datetime(2026, 5, 20, 12, 0, 0, tzinfo=UTC)

_ACTOR_A = UUID("00000000-0000-0000-0000-000000000001")
_ACTOR_B = UUID("00000000-0000-0000-0000-000000000002")
_ACTOR_C = UUID("00000000-0000-0000-0000-000000000003")

# Hamming distance 1 (1 bit flip)
_HASH_A = "0000000000000000"
_HASH_B = "0000000000000001"

# Hamming distance 64 (all bits differ) — beyond any threshold
_HASH_C = "ffffffffffffffff"


@pytest.fixture
def storage() -> SQLiteStorage:
    d = tempfile.mkdtemp()
    return SQLiteStorage(Path(d))


def _profile_env(actor_id: UUID, fw_hash: str) -> ProfileCurrentEnvelope:
    return ProfileCurrentEnvelope(
        profile_id=_new_uuid7(),
        actor_id=actor_id,
        version=1,
        role_confidence=0.5,
        stylometric_summary={"function_word_simhash": {"value": fw_hash}},
        derived_at=_NOW,
        derived_from_observation_count=1,
        trace_context=_TC,
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_close_actors_produce_proposal(storage: SQLiteStorage) -> None:
    bus = MemoryBus()
    proposals: list[LinkageProposedEnvelope] = []

    async def _capture(subject: str, payload: bytes, headers: dict[str, str]) -> None:
        proposals.append(LinkageProposedEnvelope.model_validate_json(payload))

    await bus.subscribe(SUBJECT_LINKAGE_PROPOSED, _capture)

    linker = Linker(bus=bus, storage=storage)
    await linker.on_subscribe()

    # Publish A first (seeds the index), then B (triggers comparison)
    await bus.publish(
        SUBJECT_PROFILE_CURRENT, _profile_env(_ACTOR_A, _HASH_A).model_dump_json().encode()
    )
    await asyncio.sleep(0.05)

    await bus.publish(
        SUBJECT_PROFILE_CURRENT, _profile_env(_ACTOR_B, _HASH_B).model_dump_json().encode()
    )
    await asyncio.sleep(0.1)

    assert len(proposals) >= 1
    proposal = proposals[0]
    assert {proposal.actor_a_id, proposal.actor_b_id} == {_ACTOR_A, _ACTOR_B}
    assert proposal.score > 0.0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_far_actors_produce_no_proposal(storage: SQLiteStorage) -> None:
    bus = MemoryBus()
    proposals: list[object] = []

    async def _capture(subject: str, payload: bytes, headers: dict[str, str]) -> None:
        proposals.append(payload)

    await bus.subscribe(SUBJECT_LINKAGE_PROPOSED, _capture)

    linker = Linker(bus=bus, storage=storage)
    await linker.on_subscribe()

    await bus.publish(
        SUBJECT_PROFILE_CURRENT, _profile_env(_ACTOR_A, _HASH_A).model_dump_json().encode()
    )
    await asyncio.sleep(0.05)

    await bus.publish(
        SUBJECT_PROFILE_CURRENT, _profile_env(_ACTOR_C, _HASH_C).model_dump_json().encode()
    )
    await asyncio.sleep(0.1)

    assert len(proposals) == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_proposal_persisted_to_storage(storage: SQLiteStorage) -> None:
    bus = MemoryBus()
    linker = Linker(bus=bus, storage=storage)
    await linker.on_subscribe()

    await bus.publish(
        SUBJECT_PROFILE_CURRENT, _profile_env(_ACTOR_A, _HASH_A).model_dump_json().encode()
    )
    await asyncio.sleep(0.05)
    await bus.publish(
        SUBJECT_PROFILE_CURRENT, _profile_env(_ACTOR_B, _HASH_B).model_dump_json().encode()
    )
    await asyncio.sleep(0.1)

    rows = await storage.list_linkages()
    assert len(rows) >= 1
    row = cast("LinkageRow", rows[0])
    assert {row.actor_a_id, row.actor_b_id} == {_ACTOR_A, _ACTOR_B}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_multiple_profiles_only_close_pairs_proposed(storage: SQLiteStorage) -> None:
    """A close to B, but C is far from both. Only A↔B should be proposed."""
    bus = MemoryBus()
    proposals: list[LinkageProposedEnvelope] = []

    async def _capture(subject: str, payload: bytes, headers: dict[str, str]) -> None:
        proposals.append(LinkageProposedEnvelope.model_validate_json(payload))

    await bus.subscribe(SUBJECT_LINKAGE_PROPOSED, _capture)

    linker = Linker(bus=bus, storage=storage)
    await linker.on_subscribe()

    await bus.publish(
        SUBJECT_PROFILE_CURRENT, _profile_env(_ACTOR_A, _HASH_A).model_dump_json().encode()
    )
    await asyncio.sleep(0.05)
    await bus.publish(
        SUBJECT_PROFILE_CURRENT, _profile_env(_ACTOR_B, _HASH_B).model_dump_json().encode()
    )
    await asyncio.sleep(0.05)
    await bus.publish(
        SUBJECT_PROFILE_CURRENT, _profile_env(_ACTOR_C, _HASH_C).model_dump_json().encode()
    )
    await asyncio.sleep(0.1)

    proposed_pairs = [frozenset({p.actor_a_id, p.actor_b_id}) for p in proposals]
    assert frozenset({_ACTOR_A, _ACTOR_B}) in proposed_pairs
    assert frozenset({_ACTOR_A, _ACTOR_C}) not in proposed_pairs
    assert frozenset({_ACTOR_B, _ACTOR_C}) not in proposed_pairs
