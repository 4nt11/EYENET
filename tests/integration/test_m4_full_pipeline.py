"""M4 full pipeline integration test.

Linker + Graph over MemoryBus:
1. Publish two profiles with close simhashes.
2. Linker proposes linkage.
3. Graph handles the proposal (upserts nodes + edge).
4. Confirm the linkage via storage.linkages.transition.
5. Trigger confirmed event on the bus.
6. Graph handles confirm: merges Persona, emits PersonaUpdated.
7. Verify PersonaTable + PersonaMembership + graph nodes/edges are consistent.
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
    SUBJECT_LINKAGE_CONFIRMED,
    SUBJECT_LINKAGE_PROPOSED,
    SUBJECT_PERSONA_UPDATED,
    SUBJECT_PROFILE_CURRENT,
    LinkageConfirmedEnvelope,
    LinkageProposedEnvelope,
    LinkageRow,
    PersonaRow,
    PersonaUpdatedEnvelope,
    ProfileCurrentEnvelope,
)
from eyenet.contracts.enums import LinkageState
from eyenet.graph.graph import Graph
from eyenet.linker.linker import Linker
from eyenet.models.graph import GraphEdgeType
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

_TC = TraceContext(traceparent="00-" + "a" * 32 + "-" + "b" * 16 + "-01")
_NOW = datetime(2026, 5, 20, 12, 0, 0, tzinfo=UTC)

_ACTOR_A = UUID("00000000-0000-0000-0000-000000000001")
_ACTOR_B = UUID("00000000-0000-0000-0000-000000000002")

_HASH_A = "0000000000000000"
_HASH_B = "0000000000000001"  # 1-bit Hamming distance


@pytest.fixture
def storage() -> BaseRepository:
    d = tempfile.mkdtemp()
    return get_repository(data_dir=Path(d))


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
async def test_full_m4_pipeline_linkage_propose_confirm_persona(storage: BaseRepository) -> None:
    bus = MemoryBus()
    proposals: list[LinkageProposedEnvelope] = []
    persona_updates: list[PersonaUpdatedEnvelope] = []

    async def _capture_proposal(subject: str, payload: bytes, headers: dict[str, str]) -> None:
        proposals.append(LinkageProposedEnvelope.model_validate_json(payload))

    async def _capture_persona(subject: str, payload: bytes, headers: dict[str, str]) -> None:
        persona_updates.append(PersonaUpdatedEnvelope.model_validate_json(payload))

    await bus.subscribe(SUBJECT_LINKAGE_PROPOSED, _capture_proposal)
    await bus.subscribe(SUBJECT_PERSONA_UPDATED, _capture_persona)

    linker = Linker(bus=bus, storage=storage)
    graph = Graph(bus=bus, storage=storage)

    await linker.on_subscribe()
    await graph.on_subscribe()

    # Step 1: Publish both profiles → Linker proposes, Graph handles proposal
    await bus.publish(
        SUBJECT_PROFILE_CURRENT, _profile_env(_ACTOR_A, _HASH_A).model_dump_json().encode()
    )
    await asyncio.sleep(0.1)
    await bus.publish(
        SUBJECT_PROFILE_CURRENT, _profile_env(_ACTOR_B, _HASH_B).model_dump_json().encode()
    )
    await asyncio.sleep(0.2)

    assert len(proposals) >= 1, "Linker should have proposed a linkage"

    # Verify linkage row was persisted
    rows = await storage.list_linkages()
    assert len(rows) >= 1
    linkage_row = cast("LinkageRow", rows[0])
    assert linkage_row.state == LinkageState.PROPOSED

    # Verify graph has LinkedTo edge
    edges = await storage.graph_edges_by_type(GraphEdgeType.LINKED_TO)
    assert len(edges) >= 1

    # Step 2: Confirm the linkage
    updated = cast(
        "LinkageRow",
        await storage.transition_linkage(
            linkage_row.id, LinkageState.CONFIRMED, decided_by="anti"
        ),
    )
    assert updated.state == LinkageState.CONFIRMED

    # Publish confirmed event for Graph to handle
    confirmed_env = LinkageConfirmedEnvelope.from_pair(
        _ACTOR_A,
        _ACTOR_B,
        linkage_id=linkage_row.id,
        decided_by="anti",
        decided_at=updated.decided_at or _NOW,
        trace_context=_TC,
    )
    await bus.publish(SUBJECT_LINKAGE_CONFIRMED, confirmed_env.model_dump_json().encode())
    await asyncio.sleep(0.3)

    # Step 3: Verify Persona was created
    personas = await storage.all_personas()
    assert len(personas) >= 1
    persona = personas[0]
    assert set(persona.member_actor_ids) == {_ACTOR_A, _ACTOR_B}

    # Step 4: Verify PersonaMembership reverse index
    p_a = cast("PersonaRow | None", await storage.persona_for_actor(_ACTOR_A))
    p_b = cast("PersonaRow | None", await storage.persona_for_actor(_ACTOR_B))
    assert p_a is not None
    assert p_a.id == persona.id
    assert p_b is not None
    assert p_b.id == persona.id

    # Step 5: Verify PersonaUpdated was emitted
    assert len(persona_updates) >= 1
    pu = persona_updates[0]
    assert pu.persona_id == persona.id
    assert set(pu.member_actor_ids) == {_ACTOR_A, _ACTOR_B}

    # Step 6: Verify graph has Persona node + BelongsToPersona edges
    stats = await storage.graph_stats()
    assert stats["personas"] >= 1
    belongs_edges = await storage.graph_edges_by_type(GraphEdgeType.BELONGS_TO_PERSONA)
    assert len(belongs_edges) >= 2
