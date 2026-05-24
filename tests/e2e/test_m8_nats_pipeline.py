"""E2E: M8 Verifier pipeline (Linker + Verifier + Graph) over real NATS.

Mirror of ``tests/integration/test_verifier_pipeline.py``, but driven by a
real ``nats-server`` instead of MemoryBus. Proves that subject taxonomy,
envelope wire shapes, the propose→verify→suspected promotion, and the
FeedbackPair side-effect on operator confirm all survive the actual
network hop.

Gating:
- Skipped unless ``EYENET_E2E=1``.
- If ``EYENET_NATS_URL`` is set, connect to that pre-running NATS (typical
  local loop). Otherwise spawn a fresh ``testcontainers.nats.NatsContainer``.
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
from sqlmodel import Session

from eyenet.bus import NATSBus
from eyenet.cli.config import VerifierConfig, VerifierThresholds
from eyenet.contracts._base import TraceContext, _new_uuid7
from eyenet.contracts.attribution import (
    SUBJECT_LINKAGE_PROPOSED,
    SUBJECT_LINKAGE_SUSPECTED,
    SUBJECT_PROFILE_CURRENT,
    LinkageProposedEnvelope,
    LinkageRow,
    LinkageSuspectedEnvelope,
    ProfileCurrentEnvelope,
)
from eyenet.contracts.enums import GroupKind, LinkageState, SourceKind
from eyenet.linker.linker import Linker
from eyenet.models._base import new_uuid7
from eyenet.models.message import MessageTable
from eyenet.storage import SQLiteStorage, upsert_actor, upsert_group, upsert_source
from eyenet.storage.engines import StoreName
from eyenet.storage.messages import SQLiteMessageStore
from eyenet.verifier.service import VerifierService

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        os.environ.get("EYENET_E2E") != "1",
        reason="set EYENET_E2E=1 to enable real-NATS e2e tests",
    ),
]

_TC = TraceContext(traceparent="00-" + "a" * 32 + "-" + "b" * 16 + "-01")
_NOW = datetime(2026, 5, 24, 12, 0, 0, tzinfo=UTC)

# Function-word simhash slot — 1-bit Hamming distance, well under default
# threshold of 8 bits. Use language "en" so the default Spanish-disable
# does NOT skip the comparator.
_HASH_A = "0000000000000000"
_HASH_B = "0000000000000001"


@asynccontextmanager
async def _nats_url() -> AsyncIterator[str]:
    pre_running = os.environ.get("EYENET_NATS_URL")
    if pre_running:
        yield pre_running
        return

    from testcontainers.nats import NatsContainer  # type: ignore[import-untyped]

    with NatsContainer() as nats:
        url = f"nats://{nats.get_container_host_ip()}:{nats.get_exposed_port(4222)}"
        yield url


async def _seed_actor(storage: SQLiteStorage, bodies: list[str], *, msg_prefix: str) -> UUID:
    engine = storage._engines[StoreName.MAIN]
    store = SQLiteMessageStore(engine)
    with Session(engine) as session:
        source_id = upsert_source(
            session,
            kind=SourceKind.TELEGRAM,
            display_name=f"telegram:{msg_prefix}",
            created_at=_NOW,
        )
        group_id = upsert_group(
            session,
            source_id=source_id,
            platform_groupid=f"-100-{msg_prefix}",
            kind=GroupKind.CHAT,
            title="test",
            seen_at=_NOW,
        )
        actor_id = upsert_actor(
            session,
            source_id=source_id,
            actor_key=f"actor:e2e:{msg_prefix}",
            platform_userid=msg_prefix,
            handle=None,
            display_name=None,
            seen_at=_NOW,
        )
        session.commit()
        committed_source_id = source_id
        committed_group_id = group_id

    for i, body in enumerate(bodies):
        row = MessageTable(
            id=new_uuid7(),
            source_id=committed_source_id,
            group_id=committed_group_id,
            actor_id=actor_id,
            platform_msgid=f"{msg_prefix}-{i}",
            evidence_ref=f"{msg_prefix}:-100:{i}",
            body=body,
            length_chars=len(body),
            length_words=len(body.split()),
            sent_at_source=_NOW,
            ingested_at=_NOW,
        )
        await store.put_message(row)
    return actor_id


def _profile_env(actor_id: UUID, fw_hash: str, language: str) -> ProfileCurrentEnvelope:
    return ProfileCurrentEnvelope(
        profile_id=_new_uuid7(),
        actor_id=actor_id,
        version=1,
        role_confidence=0.5,
        stylometric_summary={
            "function_word_simhash": {"value": fw_hash, "language": language},
        },
        derived_at=_NOW,
        derived_from_observation_count=1,
        trace_context=_TC,
    )


@pytest.mark.asyncio
async def test_m8_propose_verify_suspect_over_real_nats(tmp_path: Path) -> None:
    """Same-author corpora over real NATS → Linker proposes → Verifier promotes
    to SUSPECTED → row state advances → operator confirm writes FeedbackPair."""
    async with _nats_url() as url:
        bus_linker = await NATSBus.connect(url)
        bus_verifier = await NATSBus.connect(url)
        bus_capture = await NATSBus.connect(url)
        bus_publisher = await NATSBus.connect(url)
        storage = SQLiteStorage(tmp_path / "data")
        try:
            proposals: list[LinkageProposedEnvelope] = []
            suspicions: list[LinkageSuspectedEnvelope] = []

            async def _cap_proposal(_s: str, payload: bytes, _h: dict[str, str]) -> None:
                proposals.append(LinkageProposedEnvelope.model_validate_json(payload))

            async def _cap_suspect(_s: str, payload: bytes, _h: dict[str, str]) -> None:
                suspicions.append(LinkageSuspectedEnvelope.model_validate_json(payload))

            await bus_capture.subscribe(SUBJECT_LINKAGE_PROPOSED, _cap_proposal)
            await bus_capture.subscribe(SUBJECT_LINKAGE_SUSPECTED, _cap_suspect)

            # Same-author bodies → high verifier score → composite clears 0.5
            same_bodies = [
                "hola que tal compita todo bien aca",
                "muy bien gracias por preguntar amigo",
                "che mira esto que esta pasando",
            ] * 25
            actor_a = await _seed_actor(storage, same_bodies, msg_prefix="ea")
            actor_b = await _seed_actor(storage, same_bodies, msg_prefix="eb")

            linker = Linker(bus=bus_linker, storage=storage)
            verifier = VerifierService(
                bus=bus_verifier,
                storage=storage,
                config=VerifierConfig(
                    thresholds=VerifierThresholds(composite_floor=0.5),
                ),
            )

            await linker.on_subscribe()
            await verifier.on_subscribe()

            # Server-side SUB fan-out latency — see M4 e2e for rationale.
            await asyncio.sleep(0.3)

            # Drive the Linker by publishing ProfileCurrent for both actors.
            await bus_publisher.publish(
                SUBJECT_PROFILE_CURRENT,
                _profile_env(actor_a, _HASH_A, language="en").model_dump_json().encode(),
            )
            await asyncio.sleep(0.5)
            await bus_publisher.publish(
                SUBJECT_PROFILE_CURRENT,
                _profile_env(actor_b, _HASH_B, language="en").model_dump_json().encode(),
            )
            # Allow propose → verify → suspect → state update to complete.
            await asyncio.sleep(1.5)

            assert proposals, "Linker should have proposed a linkage over NATS"
            assert suspicions, "Verifier should have promoted to SUSPECTED"
            assert proposals[0].evidence.get("language") == "en"

            rows = await storage.linkages.list_linkages()
            assert len(rows) >= 1
            linkage_row = cast("LinkageRow", rows[0])
            assert linkage_row.state == LinkageState.SUSPECTED

            # Operator confirm → FeedbackPair side-effect.
            await storage.linkages.transition(
                linkage_row.id, LinkageState.CONFIRMED, decided_by="anti"
            )
            await storage.feedback_pairs.record(
                linkage_id=linkage_row.id,
                actor_a=linkage_row.actor_a_id,
                actor_b=linkage_row.actor_b_id,
                ground_truth="same",
                decided_by="anti",
                decided_at=datetime.now(tz=UTC),
            )
            feedback = await storage.feedback_pairs.get(linkage_row.id)
            assert feedback is not None
            assert feedback.ground_truth == "same"
        finally:
            await linker.shutdown()
            await verifier.shutdown()
            await bus_linker.close()
            await bus_verifier.close()
            await bus_capture.close()
            await bus_publisher.close()
            await storage.close()


@pytest.mark.asyncio
async def test_m8_diff_author_no_promotion_over_real_nats(tmp_path: Path) -> None:
    """Different-author corpora → Linker proposes (bits are still close) →
    Verifier composite below floor → no SUSPECTED, no state transition."""
    async with _nats_url() as url:
        bus_linker = await NATSBus.connect(url)
        bus_verifier = await NATSBus.connect(url)
        bus_capture = await NATSBus.connect(url)
        bus_publisher = await NATSBus.connect(url)
        storage = SQLiteStorage(tmp_path / "data")
        try:
            suspicions: list[bytes] = []

            async def _cap_suspect(_s: str, payload: bytes, _h: dict[str, str]) -> None:
                suspicions.append(payload)

            await bus_capture.subscribe(SUBJECT_LINKAGE_SUSPECTED, _cap_suspect)

            # Different-vocabulary bodies, same simhash bit-pattern.
            body_a = ["hello world how are you today friend good morning"] * 80
            body_b = ["hola estimado caballero gracias por venir esta noche"] * 80
            actor_a = await _seed_actor(storage, body_a, msg_prefix="da")
            actor_b = await _seed_actor(storage, body_b, msg_prefix="db")

            linker = Linker(bus=bus_linker, storage=storage)
            verifier = VerifierService(
                bus=bus_verifier,
                storage=storage,
                # Floor 0.75 — well above what diff-author should produce.
                config=VerifierConfig(
                    thresholds=VerifierThresholds(composite_floor=0.75),
                ),
            )

            await linker.on_subscribe()
            await verifier.on_subscribe()
            await asyncio.sleep(0.3)

            await bus_publisher.publish(
                SUBJECT_PROFILE_CURRENT,
                _profile_env(actor_a, _HASH_A, language="en").model_dump_json().encode(),
            )
            await asyncio.sleep(0.5)
            await bus_publisher.publish(
                SUBJECT_PROFILE_CURRENT,
                _profile_env(actor_b, _HASH_B, language="en").model_dump_json().encode(),
            )
            await asyncio.sleep(1.5)

            assert not suspicions, "Verifier must not promote diff-author pair"

            rows = await storage.linkages.list_linkages()
            assert len(rows) >= 1
            assert cast("LinkageRow", rows[0]).state == LinkageState.PROPOSED
        finally:
            await linker.shutdown()
            await verifier.shutdown()
            await bus_linker.close()
            await bus_verifier.close()
            await bus_capture.close()
            await bus_publisher.close()
            await storage.close()
