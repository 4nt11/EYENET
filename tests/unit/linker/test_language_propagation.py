"""M8 fix: Linker must propagate slot_language into LinkageProposed.evidence.

Without this propagation, the Verifier's per-language `None`-disable path
is unreachable at runtime because LinkageProposedEnvelope doesn't carry
language anywhere else. See M8 gap-closure plan #2.
"""

from __future__ import annotations

import asyncio
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from eyenet.bus import MemoryBus
from eyenet.contracts._base import TraceContext, _new_uuid7
from eyenet.contracts.attribution import (
    SUBJECT_LINKAGE_PROPOSED,
    SUBJECT_PROFILE_CURRENT,
    LinkageProposedEnvelope,
    ProfileCurrentEnvelope,
)
from eyenet.linker.linker import Linker
from eyenet.storage.factory import get_repository

_TC = TraceContext(traceparent="00-" + "a" * 32 + "-" + "b" * 16 + "-01")
_NOW = datetime(2026, 5, 24, 12, 0, 0, tzinfo=UTC)

_ACTOR_A = UUID("00000000-0000-0000-0000-0000000000a1")
_ACTOR_B = UUID("00000000-0000-0000-0000-0000000000a2")

_HASH_A = "0000000000000000"
_HASH_B = "0000000000000001"  # 1-bit Hamming distance


def _profile_env(actor_id: UUID, fw_hash: str, language: str | None) -> ProfileCurrentEnvelope:
    slot: dict[str, object] = {"value": fw_hash}
    if language is not None:
        slot["language"] = language
    return ProfileCurrentEnvelope(
        profile_id=_new_uuid7(),
        actor_id=actor_id,
        version=1,
        role_confidence=0.5,
        stylometric_summary={"function_word_simhash": slot},
        derived_at=_NOW,
        derived_from_observation_count=1,
        trace_context=_TC,
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_proposal_carries_slot_language() -> None:
    """When the comparator reports a slot_language, it lands in evidence."""
    bus = MemoryBus()
    storage = get_repository(data_dir=Path(tempfile.mkdtemp()))
    proposals: list[LinkageProposedEnvelope] = []

    async def _capture(_s: str, payload: bytes, _h: dict[str, str]) -> None:
        proposals.append(LinkageProposedEnvelope.model_validate_json(payload))

    await bus.subscribe(SUBJECT_LINKAGE_PROPOSED, _capture)

    # The default LinkerThresholds disables function_word for "es" — pick
    # a non-disabled language so the comparator actually runs.
    linker = Linker(bus=bus, storage=storage)
    await linker.on_subscribe()

    await bus.publish(
        SUBJECT_PROFILE_CURRENT,
        _profile_env(_ACTOR_A, _HASH_A, language="en").model_dump_json().encode(),
    )
    await asyncio.sleep(0.05)
    await bus.publish(
        SUBJECT_PROFILE_CURRENT,
        _profile_env(_ACTOR_B, _HASH_B, language="en").model_dump_json().encode(),
    )
    await asyncio.sleep(0.1)

    assert proposals, "expected at least one LinkageProposed"
    assert proposals[0].evidence.get("language") == "en"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_proposal_omits_language_when_slot_has_none() -> None:
    """Profile without slot language → evidence has no `language` key."""
    bus = MemoryBus()
    storage = get_repository(data_dir=Path(tempfile.mkdtemp()))
    proposals: list[LinkageProposedEnvelope] = []

    async def _capture(_s: str, payload: bytes, _h: dict[str, str]) -> None:
        proposals.append(LinkageProposedEnvelope.model_validate_json(payload))

    await bus.subscribe(SUBJECT_LINKAGE_PROPOSED, _capture)

    linker = Linker(bus=bus, storage=storage)
    await linker.on_subscribe()

    await bus.publish(
        SUBJECT_PROFILE_CURRENT,
        _profile_env(_ACTOR_A, _HASH_A, language=None).model_dump_json().encode(),
    )
    await asyncio.sleep(0.05)
    await bus.publish(
        SUBJECT_PROFILE_CURRENT,
        _profile_env(_ACTOR_B, _HASH_B, language=None).model_dump_json().encode(),
    )
    await asyncio.sleep(0.1)

    assert proposals, "expected at least one LinkageProposed"
    assert "language" not in proposals[0].evidence
