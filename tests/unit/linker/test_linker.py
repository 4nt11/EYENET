"""Unit tests for the Linker service — pre-seed VectorIndex, publish profile, assert proposal."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import pytest

from eyenet.bus import MemoryBus
from eyenet.cli.config import LinkerConfig, LinkerThresholds
from eyenet.contracts._base import TraceContext, _new_uuid7
from eyenet.contracts.attribution import (
    SUBJECT_LINKAGE_PROPOSED,
    SUBJECT_PROFILE_CURRENT,
    LinkageProposedEnvelope,
    LinkageRow,
    ProfileCurrentEnvelope,
)
from eyenet.linker.linker import Linker
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

_TC = TraceContext(traceparent="00-" + "a" * 32 + "-" + "b" * 16 + "-01")
_NOW = datetime(2026, 5, 20, 12, 0, 0, tzinfo=UTC)

_ACTOR_A = UUID("00000000-0000-0000-0000-000000000001")
_ACTOR_B = UUID("00000000-0000-0000-0000-000000000002")

_CLOSE_HASH = "0000000000000001"  # distance 1 from 0x0000000000000000
_FAR_HASH = "ffffffffffffffff"  # distance 64 from 0x0000000000000000
_BASE_HASH = "0000000000000000"


@pytest.fixture
def storage(tmp_path: object) -> BaseRepository:
    import tempfile
    from pathlib import Path

    d = tempfile.mkdtemp()
    return get_repository(data_dir=Path(d))


@pytest.fixture
def bus() -> MemoryBus:
    return MemoryBus()


def _profile_envelope(
    actor_id: UUID, fw_hash: str | None = None, cn_hash: str | None = None
) -> ProfileCurrentEnvelope:
    stylometric: dict[str, object] = {}
    if fw_hash is not None:
        stylometric["function_word_simhash"] = {"value": fw_hash}
    if cn_hash is not None:
        stylometric["char_ngram_simhash"] = {"value": cn_hash}
    return ProfileCurrentEnvelope(
        profile_id=_new_uuid7(),
        actor_id=actor_id,
        version=1,
        role_confidence=0.5,
        stylometric_summary=stylometric,
        derived_at=_NOW,
        derived_from_observation_count=1,
        trace_context=_TC,
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_linker_proposes_close_actors(storage: BaseRepository, bus: MemoryBus) -> None:
    """Pre-seed actor B's simhash. Publish actor A with close hash → proposal emitted."""
    proposed_envelopes: list[LinkageProposedEnvelope] = []

    async def _capture(subject: str, payload: bytes, headers: dict[str, str]) -> None:
        proposed_envelopes.append(LinkageProposedEnvelope.model_validate_json(payload))

    await bus.subscribe(SUBJECT_LINKAGE_PROPOSED, _capture)

    # Pre-seed actor B so it's in the index
    await storage.upsert_simhash(
        _ACTOR_B, "function_word_distribution_top50", _BASE_HASH
    )

    # Create linker with default thresholds (fw = 8)
    linker = Linker(bus=bus, storage=storage)
    await linker.on_subscribe()

    # Publish actor A profile with close hash
    env_a = _profile_envelope(_ACTOR_A, fw_hash=_CLOSE_HASH)
    await bus.publish(SUBJECT_PROFILE_CURRENT, env_a.model_dump_json().encode())

    # Allow the create_task to execute
    await asyncio.sleep(0.05)

    assert len(proposed_envelopes) >= 1
    proposal = proposed_envelopes[0]
    assert {proposal.actor_a_id, proposal.actor_b_id} == {_ACTOR_A, _ACTOR_B}
    assert proposal.method == "function_word_simhash_hamming"
    assert proposal.score > 0.0
    assert proposal.actor_a_id < proposal.actor_b_id


@pytest.mark.unit
@pytest.mark.asyncio
async def test_linker_no_proposal_when_far(storage: BaseRepository, bus: MemoryBus) -> None:
    """Pre-seed actor B with a hash that is beyond threshold → no proposal."""
    proposed_envelopes: list[object] = []

    async def _capture(subject: str, payload: bytes, headers: dict[str, str]) -> None:
        proposed_envelopes.append(payload)

    await bus.subscribe(SUBJECT_LINKAGE_PROPOSED, _capture)

    # Pre-seed B with a hash very far from the one A will use
    await storage.upsert_simhash(
        _ACTOR_B, "function_word_distribution_top50", _FAR_HASH
    )

    linker = Linker(bus=bus, storage=storage)
    await linker.on_subscribe()

    env_a = _profile_envelope(_ACTOR_A, fw_hash=_BASE_HASH)
    await bus.publish(SUBJECT_PROFILE_CURRENT, env_a.model_dump_json().encode())
    await asyncio.sleep(0.05)

    assert len(proposed_envelopes) == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_linker_no_self_proposal(storage: BaseRepository, bus: MemoryBus) -> None:
    """Actor should never propose a linkage to itself."""
    proposed_envelopes: list[object] = []

    async def _capture(subject: str, payload: bytes, headers: dict[str, str]) -> None:
        proposed_envelopes.append(LinkageProposedEnvelope.model_validate_json(payload))

    await bus.subscribe(SUBJECT_LINKAGE_PROPOSED, _capture)

    linker = Linker(bus=bus, storage=storage)
    await linker.on_subscribe()

    env = _profile_envelope(_ACTOR_A, fw_hash=_BASE_HASH)
    await bus.publish(SUBJECT_PROFILE_CURRENT, env.model_dump_json().encode())
    await asyncio.sleep(0.05)

    for p in proposed_envelopes:
        assert isinstance(p, LinkageProposedEnvelope)
        assert _ACTOR_A not in (p.actor_a_id, p.actor_b_id) or p.actor_a_id != p.actor_b_id


@pytest.mark.unit
@pytest.mark.asyncio
async def test_linker_persists_proposed_row(storage: BaseRepository, bus: MemoryBus) -> None:
    """Proposed linkage is persisted to storage.linkages."""
    await storage.upsert_simhash(
        _ACTOR_B, "function_word_distribution_top50", _BASE_HASH
    )

    linker = Linker(bus=bus, storage=storage)
    await linker.on_subscribe()

    env_a = _profile_envelope(_ACTOR_A, fw_hash=_CLOSE_HASH)
    await bus.publish(SUBJECT_PROFILE_CURRENT, env_a.model_dump_json().encode())
    await asyncio.sleep(0.05)

    rows = await storage.list_linkages()
    assert len(rows) >= 1
    row = cast("LinkageRow", rows[0])
    assert {row.actor_a_id, row.actor_b_id} == {_ACTOR_A, _ACTOR_B}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_linker_skips_missing_slot(storage: BaseRepository, bus: MemoryBus) -> None:
    """Profile with no stylometric slots emits no proposals and does not error."""
    proposed: list[object] = []

    async def _capture(subject: str, payload: bytes, headers: dict[str, str]) -> None:
        proposed.append(payload)

    await bus.subscribe(SUBJECT_LINKAGE_PROPOSED, _capture)

    linker = Linker(bus=bus, storage=storage)
    await linker.on_subscribe()

    env = _profile_envelope(_ACTOR_A)  # no hashes
    await bus.publish(SUBJECT_PROFILE_CURRENT, env.model_dump_json().encode())
    await asyncio.sleep(0.05)

    assert len(proposed) == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_linker_respects_config_threshold(storage: BaseRepository, bus: MemoryBus) -> None:
    """With threshold=0, only identical hashes match."""
    proposed: list[object] = []

    async def _capture(subject: str, payload: bytes, headers: dict[str, str]) -> None:
        proposed.append(payload)

    await bus.subscribe(SUBJECT_LINKAGE_PROPOSED, _capture)

    # Pre-seed B with distance-1 hash
    await storage.upsert_simhash(
        _ACTOR_B, "function_word_distribution_top50", _CLOSE_HASH
    )

    # Zero threshold means only distance=0 matches
    cfg = LinkerConfig(thresholds=LinkerThresholds(function_word_simhash_hamming=0))
    linker = Linker(bus=bus, storage=storage, config=cfg)
    await linker.on_subscribe()

    env = _profile_envelope(_ACTOR_A, fw_hash=_BASE_HASH)
    await bus.publish(SUBJECT_PROFILE_CURRENT, env.model_dump_json().encode())
    await asyncio.sleep(0.05)

    assert len(proposed) == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_linker_skips_comparator_disabled_for_language(
    storage: BaseRepository, bus: MemoryBus
) -> None:
    """A None per-language threshold disables the comparator for that language.

    Spanish-specific use case (M5 / Rutify 2026-05-22): simhash signal is
    too weak on short Spanish chat to support precision ≥ 0.70. We disable
    rather than ship noise.
    """
    proposed: list[object] = []

    async def _capture(subject: str, payload: bytes, headers: dict[str, str]) -> None:
        proposed.append(payload)

    await bus.subscribe(SUBJECT_LINKAGE_PROPOSED, _capture)

    # Pre-seed actor B with a CLOSE hash — under default thresholds this
    # would absolutely emit a proposal. The Spanish disable must override.
    await storage.upsert_simhash(
        _ACTOR_B, "function_word_distribution_top50", _BASE_HASH
    )

    cfg = LinkerConfig(
        thresholds=LinkerThresholds(
            function_word_simhash_hamming=8,
            function_word_simhash_hamming_per_lang={"es": None},
        )
    )
    linker = Linker(bus=bus, storage=storage, config=cfg)
    await linker.on_subscribe()

    # Profile carries language="es" → comparator must skip.
    env = _profile_envelope(_ACTOR_A, fw_hash=_CLOSE_HASH)
    fw_slot = env.stylometric_summary["function_word_simhash"]
    assert isinstance(fw_slot, dict)
    fw_slot["language"] = "es"
    await bus.publish(SUBJECT_PROFILE_CURRENT, env.model_dump_json().encode())
    await asyncio.sleep(0.05)

    assert len(proposed) == 0
