"""E2E: full M4 pipeline (Linker + Graph + Persona) over real NATS.

Mirror of `tests/integration/test_m4_full_pipeline.py`, but driven by a real
`nats-server` instead of `MemoryBus`. Proves the M4 services agree on subject
taxonomy, envelope wire shapes, and persona merge timing when the bus actually
hops through the network.

Gating:
- Skipped unless `EYENET_E2E=1`.
- If `EYENET_NATS_URL` is set, connect to that pre-running NATS (typical local
  loop where ANTI already has `nats-server` running). Otherwise spawn a fresh
  `testcontainers.nats.NatsContainer` (CI-friendly, hermetic).
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest

from eyenet.bus import NATSBus
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
from eyenet.storage import SQLiteStorage

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        os.environ.get("EYENET_E2E") != "1",
        reason="set EYENET_E2E=1 to enable real-NATS e2e tests",
    ),
]

_TC = TraceContext(traceparent="00-" + "a" * 32 + "-" + "b" * 16 + "-01")
_NOW = datetime(2026, 5, 22, 12, 0, 0, tzinfo=UTC)

_ACTOR_A = UUID("00000000-0000-0000-0000-000000000001")
_ACTOR_B = UUID("00000000-0000-0000-0000-000000000002")

_HASH_A = "0000000000000000"
_HASH_B = "0000000000000001"  # 1-bit Hamming distance — well under both thresholds


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


@asynccontextmanager
async def _nats_url() -> AsyncIterator[str]:
    """Yield a NATS URL; prefer EYENET_NATS_URL, else spin testcontainers."""

    pre_running = os.environ.get("EYENET_NATS_URL")
    if pre_running:
        yield pre_running
        return

    from testcontainers.nats import NatsContainer  # type: ignore[import-untyped]

    with NatsContainer() as nats:
        url = f"nats://{nats.get_container_host_ip()}:{nats.get_exposed_port(4222)}"
        yield url


@pytest.mark.asyncio
async def test_full_m4_pipeline_over_real_nats(tmp_path: Path) -> None:  # noqa: PLR0915
    # Linear narrative on purpose — mirrors the operator e2e story. Splitting
    # this into helpers obscures the propose→confirm→persona walk.
    async with _nats_url() as url:
        bus_linker = await NATSBus.connect(url)
        bus_graph = await NATSBus.connect(url)
        bus_capture = await NATSBus.connect(url)
        bus_publisher = await NATSBus.connect(url)
        storage = SQLiteStorage(tmp_path / "data")
        try:
            proposals: list[LinkageProposedEnvelope] = []
            persona_updates: list[PersonaUpdatedEnvelope] = []

            async def _capture_proposal(
                _subject: str, payload: bytes, _headers: dict[str, str]
            ) -> None:
                proposals.append(LinkageProposedEnvelope.model_validate_json(payload))

            async def _capture_persona(
                _subject: str, payload: bytes, _headers: dict[str, str]
            ) -> None:
                persona_updates.append(PersonaUpdatedEnvelope.model_validate_json(payload))

            await bus_capture.subscribe(SUBJECT_LINKAGE_PROPOSED, _capture_proposal)
            await bus_capture.subscribe(SUBJECT_PERSONA_UPDATED, _capture_persona)

            linker = Linker(bus=bus_linker, storage=storage)
            graph = Graph(bus=bus_graph, storage=storage)

            await linker.on_subscribe()
            await graph.on_subscribe()

            # NATS SUB registrations are async server-side and live on different
            # connections than the publisher — give the server a beat to fan the
            # subscriptions out before publishing, or the first PUB races the SUBs.
            await asyncio.sleep(0.3)

            # Step 1 — publish both profiles; Linker proposes, Graph upserts.
            await bus_publisher.publish(
                SUBJECT_PROFILE_CURRENT,
                _profile_env(_ACTOR_A, _HASH_A).model_dump_json().encode(),
            )
            await asyncio.sleep(0.5)
            await bus_publisher.publish(
                SUBJECT_PROFILE_CURRENT,
                _profile_env(_ACTOR_B, _HASH_B).model_dump_json().encode(),
            )
            await asyncio.sleep(0.8)

            assert len(proposals) >= 1, "Linker should have proposed a linkage over NATS"

            rows = await storage.list_linkages()
            assert len(rows) >= 1
            linkage_row = cast("LinkageRow", rows[0])
            assert linkage_row.state == LinkageState.PROPOSED

            edges = await storage.graph_edges_by_type(GraphEdgeType.LINKED_TO)
            assert len(edges) >= 1

            # Step 2 — operator confirms the linkage; publish `linkage.confirmed`.
            updated = cast(
                "LinkageRow",
                await storage.transition_linkage(
                    linkage_row.id, LinkageState.CONFIRMED, decided_by="anti"
                ),
            )
            assert updated.state == LinkageState.CONFIRMED

            confirmed_env = LinkageConfirmedEnvelope.from_pair(
                _ACTOR_A,
                _ACTOR_B,
                linkage_id=linkage_row.id,
                decided_by="anti",
                decided_at=updated.decided_at or _NOW,
                trace_context=_TC,
            )
            await bus_publisher.publish(
                SUBJECT_LINKAGE_CONFIRMED, confirmed_env.model_dump_json().encode()
            )
            await asyncio.sleep(0.8)

            # Step 3 — Persona created.
            personas = await storage.all_personas()
            assert len(personas) >= 1
            persona = personas[0]
            assert set(persona.member_actor_ids) == {_ACTOR_A, _ACTOR_B}

            # Step 4 — PersonaMembership reverse index resolves both actors.
            p_a = cast("PersonaRow | None", await storage.persona_for_actor(_ACTOR_A))
            p_b = cast("PersonaRow | None", await storage.persona_for_actor(_ACTOR_B))
            assert p_a is not None
            assert p_a.id == persona.id
            assert p_b is not None
            assert p_b.id == persona.id

            # Step 5 — PersonaUpdated event observed on the bus.
            assert len(persona_updates) >= 1
            pu = persona_updates[0]
            assert pu.persona_id == persona.id
            assert set(pu.member_actor_ids) == {_ACTOR_A, _ACTOR_B}

            # Step 6 — Graph has Persona node + BelongsToPersona edges.
            stats = await storage.graph_stats()
            assert stats["personas"] >= 1
            belongs_edges = await storage.graph_edges_by_type(GraphEdgeType.BELONGS_TO_PERSONA)
            assert len(belongs_edges) >= 2
        finally:
            await bus_linker.close()
            await bus_graph.close()
            await bus_capture.close()
            await bus_publisher.close()
            await storage.close()
