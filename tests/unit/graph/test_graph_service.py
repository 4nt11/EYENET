"""Unit tests for the Graph service — each handler's effect on storage."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID

import pytest

from eyenet.bus import MemoryBus
from eyenet.contracts._base import TraceContext, _new_uuid7
from eyenet.contracts.attribution import (
    SUBJECT_LINKAGE_CONFIRMED,
    SUBJECT_LINKAGE_PROPOSED,
    SUBJECT_LINKAGE_REJECTED,
    SUBJECT_LINKAGE_SUSPECTED,
    SUBJECT_PERSONA_MERGE,
    SUBJECT_PERSONA_SPLIT,
    SUBJECT_PERSONA_UPDATED,
    SUBJECT_PROFILE_CURRENT,
    LinkageConfirmedEnvelope,
    LinkageProposedEnvelope,
    LinkageRejectedEnvelope,
    LinkageSuspectedEnvelope,
    PersonaMergeCommandEnvelope,
    PersonaSplitCommandEnvelope,
    PersonaUpdatedEnvelope,
    ProfileCurrentEnvelope,
)
from eyenet.graph.graph import Graph
from eyenet.models.graph import GraphEdgeType
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

_TC = TraceContext(traceparent="00-" + "a" * 32 + "-" + "b" * 16 + "-01")
_NOW = datetime(2026, 5, 20, 12, 0, 0, tzinfo=UTC)

_ACTOR_A = UUID("00000000-0000-0000-0000-000000000001")
_ACTOR_B = UUID("00000000-0000-0000-0000-000000000002")
_LID = UUID("00000000-0000-0000-0000-000000000099")


@pytest.fixture
def storage(tmp_path: object) -> BaseRepository:
    import tempfile
    from pathlib import Path

    d = tempfile.mkdtemp()
    return get_repository(data_dir=Path(d))


@pytest.fixture
def bus() -> MemoryBus:
    return MemoryBus()


def _profile_env(actor_id: UUID) -> ProfileCurrentEnvelope:
    return ProfileCurrentEnvelope(
        profile_id=_new_uuid7(),
        actor_id=actor_id,
        version=1,
        role_confidence=0.5,
        derived_at=_NOW,
        derived_from_observation_count=1,
        trace_context=_TC,
    )


def _proposed_env() -> LinkageProposedEnvelope:
    return LinkageProposedEnvelope.from_pair(
        _ACTOR_A,
        _ACTOR_B,
        linkage_id=_LID,
        method="function_word_simhash_hamming",
        score=0.9,
        evidence={"distance": 2},
        proposed_at=_NOW,
        trace_context=_TC,
    )


def _suspected_env() -> LinkageSuspectedEnvelope:
    return LinkageSuspectedEnvelope.from_pair(
        _ACTOR_A,
        _ACTOR_B,
        linkage_id=_LID,
        decided_by="anti",
        decided_at=_NOW,
        trace_context=_TC,
    )


def _confirmed_env() -> LinkageConfirmedEnvelope:
    return LinkageConfirmedEnvelope.from_pair(
        _ACTOR_A,
        _ACTOR_B,
        linkage_id=_LID,
        decided_by="anti",
        decided_at=_NOW,
        trace_context=_TC,
    )


def _rejected_env() -> LinkageRejectedEnvelope:
    return LinkageRejectedEnvelope.from_pair(
        _ACTOR_A,
        _ACTOR_B,
        linkage_id=_LID,
        decided_by="anti",
        decided_at=_NOW,
        trace_context=_TC,
    )


async def _start_graph(bus: MemoryBus, storage: BaseRepository) -> Graph:
    graph = Graph(bus=bus, storage=storage)
    await graph.on_subscribe()
    return graph


@pytest.mark.unit
@pytest.mark.asyncio
async def test_profile_current_upserts_actor_node(storage: BaseRepository, bus: MemoryBus) -> None:
    await _start_graph(bus, storage)
    env = _profile_env(_ACTOR_A)
    await bus.publish(SUBJECT_PROFILE_CURRENT, env.model_dump_json().encode())
    await asyncio.sleep(0.05)

    stats = await storage.graph_stats()
    assert stats["actors"] >= 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_linkage_proposed_upserts_both_actor_nodes(
    storage: BaseRepository, bus: MemoryBus
) -> None:
    await _start_graph(bus, storage)
    env = _proposed_env()
    await bus.publish(SUBJECT_LINKAGE_PROPOSED, env.model_dump_json().encode())
    await asyncio.sleep(0.05)

    stats = await storage.graph_stats()
    assert stats["actors"] >= 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_linkage_proposed_upserts_linked_to_edge(
    storage: BaseRepository, bus: MemoryBus
) -> None:
    await _start_graph(bus, storage)
    env = _proposed_env()
    await bus.publish(SUBJECT_LINKAGE_PROPOSED, env.model_dump_json().encode())
    await asyncio.sleep(0.05)

    edges = await storage.graph_edges_by_type(GraphEdgeType.LINKED_TO)
    assert len(edges) >= 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_linkage_suspected_updates_edge_state(
    storage: BaseRepository, bus: MemoryBus
) -> None:
    await _start_graph(bus, storage)

    # First propose, then suspect
    await bus.publish(SUBJECT_LINKAGE_PROPOSED, _proposed_env().model_dump_json().encode())
    await asyncio.sleep(0.05)
    await bus.publish(SUBJECT_LINKAGE_SUSPECTED, _suspected_env().model_dump_json().encode())
    await asyncio.sleep(0.05)

    edges = await storage.graph_edges_by_type(GraphEdgeType.LINKED_TO)
    assert any(e[2].get("state") == "suspected" for e in edges)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_linkage_rejected_updates_edge_state(storage: BaseRepository, bus: MemoryBus) -> None:
    await _start_graph(bus, storage)

    await bus.publish(SUBJECT_LINKAGE_PROPOSED, _proposed_env().model_dump_json().encode())
    await asyncio.sleep(0.05)
    await bus.publish(SUBJECT_LINKAGE_REJECTED, _rejected_env().model_dump_json().encode())
    await asyncio.sleep(0.05)

    edges = await storage.graph_edges_by_type(GraphEdgeType.LINKED_TO)
    assert any(e[2].get("state") == "rejected" for e in edges)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_linkage_confirmed_creates_persona(storage: BaseRepository, bus: MemoryBus) -> None:
    await _start_graph(bus, storage)

    # Pre-seed the linkage row first — Graph's confirm handler calls personas.merge_actors
    # which requires the linkage UUID to already exist in storage.
    await storage.insert_proposed_linkage(
        _ACTOR_A, _ACTOR_B, method="function_word_simhash_hamming", score=0.9, evidence={}
    )

    await bus.publish(SUBJECT_LINKAGE_PROPOSED, _proposed_env().model_dump_json().encode())
    await asyncio.sleep(0.05)
    await bus.publish(SUBJECT_LINKAGE_CONFIRMED, _confirmed_env().model_dump_json().encode())
    await asyncio.sleep(0.1)

    personas = await storage.all_personas()
    assert len(personas) >= 1
    persona = personas[0]
    assert set(persona.member_actor_ids) == {_ACTOR_A, _ACTOR_B}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_linkage_confirmed_emits_persona_updated(
    storage: BaseRepository, bus: MemoryBus
) -> None:
    persona_updates: list[PersonaUpdatedEnvelope] = []

    async def _capture(subject: str, payload: bytes, headers: dict[str, str]) -> None:
        persona_updates.append(PersonaUpdatedEnvelope.model_validate_json(payload))

    await bus.subscribe(SUBJECT_PERSONA_UPDATED, _capture)
    await _start_graph(bus, storage)

    await storage.insert_proposed_linkage(
        _ACTOR_A, _ACTOR_B, method="function_word_simhash_hamming", score=0.9, evidence={}
    )
    await bus.publish(SUBJECT_LINKAGE_PROPOSED, _proposed_env().model_dump_json().encode())
    await asyncio.sleep(0.05)
    await bus.publish(SUBJECT_LINKAGE_CONFIRMED, _confirmed_env().model_dump_json().encode())
    await asyncio.sleep(0.1)

    assert len(persona_updates) >= 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_linkage_confirmed_upserts_persona_node(
    storage: BaseRepository, bus: MemoryBus
) -> None:
    await _start_graph(bus, storage)
    await storage.insert_proposed_linkage(
        _ACTOR_A, _ACTOR_B, method="function_word_simhash_hamming", score=0.9, evidence={}
    )
    await bus.publish(SUBJECT_LINKAGE_PROPOSED, _proposed_env().model_dump_json().encode())
    await asyncio.sleep(0.05)
    await bus.publish(SUBJECT_LINKAGE_CONFIRMED, _confirmed_env().model_dump_json().encode())
    await asyncio.sleep(0.1)

    stats = await storage.graph_stats()
    assert stats["actors"] >= 2
    assert stats["personas"] >= 1
    belongs_edges = await storage.graph_edges_by_type(GraphEdgeType.BELONGS_TO_PERSONA)
    assert len(belongs_edges) >= 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_persona_merge_command_merges_two_personas(
    storage: BaseRepository, bus: MemoryBus
) -> None:
    await _start_graph(bus, storage)
    a1, a2, b1, b2 = _new_uuid7(), _new_uuid7(), _new_uuid7(), _new_uuid7()
    p1 = await storage.merge_actors_into_persona(*sorted([a1, a2]))
    p2 = await storage.merge_actors_into_persona(*sorted([b1, b2]))
    assert p1.id != p2.id

    seen: list[str] = []

    async def _rec(s: str, _p: bytes, _h: dict[str, str]) -> None:
        seen.append(s)

    await bus.subscribe(SUBJECT_PERSONA_UPDATED, _rec)

    env = PersonaMergeCommandEnvelope(
        persona_id=p1.id,
        other_persona_id=p2.id,
        decided_by="op",
        decided_at=_NOW,
        reason="same human",
        trace_context=_TC,
    )
    await bus.publish(SUBJECT_PERSONA_MERGE, env.model_dump_json().encode())
    await asyncio.sleep(0.05)

    resolved = {(await storage.persona_for_actor(a)).id for a in (a1, a2, b1, b2)}
    assert len(resolved) == 1, "merge command must union both personas"
    assert SUBJECT_PERSONA_UPDATED in seen, "Graph must emit persona.updated after applying"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_persona_split_command_removes_actor(storage: BaseRepository, bus: MemoryBus) -> None:
    await _start_graph(bus, storage)
    a1, a2 = sorted([_new_uuid7(), _new_uuid7()])
    persona = await storage.merge_actors_into_persona(a1, a2)

    env = PersonaSplitCommandEnvelope(
        persona_id=persona.id,
        actor_id=a1,
        decided_by="op",
        decided_at=_NOW,
        reason="over-linked",
        trace_context=_TC,
    )
    await bus.publish(SUBJECT_PERSONA_SPLIT, env.model_dump_json().encode())
    await asyncio.sleep(0.05)

    assert await storage.persona_for_actor(a1) is None, "split actor must leave the persona"
    remaining = await storage.persona_for_actor(a2)
    assert remaining is not None and a2 in remaining.member_actor_ids
