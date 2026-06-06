"""Integration test for the DiscoverySensor (M9.E2).

Drives the full envelope → resolved MessageContext → extractor-run path against
a real in-memory repository: a raw message containing a channel reference and a
URL must yield a GroupCandidateMention (at the right depth + seed root) and an
InfrastructureArtifact. The bus subscription itself is trivial wiring identical
to the proven StylometricSensor, so we exercise `_dispatch` directly.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from eyenet.bus.memory import MemoryBus
from eyenet.contracts.collector import compute_instance_id
from eyenet.contracts.enums import (
    CandidateState,
    GroupKind,
    ResolutionState,
    SourceDomainPatternKind,
    SourceKind,
)
from eyenet.contracts.raw_message import RawMessageEnvelope
from eyenet.models.message import MessageTable
from eyenet.sensor.discovery_sensor import DiscoverySensor
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

_NOW = datetime(2026, 6, 6, tzinfo=UTC)
pytestmark = pytest.mark.integration


async def _seed(storage: BaseRepository) -> tuple[str, str, UUID, UUID]:
    """Seed source/identity/collector/actor/group/message; return
    (instance_id, evidence_ref, root_group_id, source_id)."""
    src = await storage.upsert_source(
        kind=SourceKind.TELEGRAM, display_name="telegram:s", created_at=_NOW
    )
    # a SourceDomain so the extracted URL artifact resolves to this source
    await storage.add_source_domain(
        source_id=src,
        pattern="evil.example",
        pattern_kind=SourceDomainPatternKind.EXACT,
        is_primary=True,
        created_at=_NOW,
    )
    ident = await storage.create_identity(name="tg_alpha", source_id=src, session_path="/a")
    await storage.create_collector(
        instance_name="collector-alpha",
        kind=SourceKind.TELEGRAM,
        source_id=src,
        identity_id=ident.id,
        config={},
        created_at=_NOW,
        created_by_user_id=UUID(int=1),
    )
    actor_id = await storage.upsert_actor(
        source_id=src,
        actor_key="actor:1",
        platform_userid="1",
        handle="poster",
        display_name=None,
        seen_at=_NOW,
    )
    root_group = await storage.upsert_group(
        source_id=src,
        platform_groupid="rootgroup",
        kind=GroupKind.CHANNEL,
        title="root",
        seen_at=_NOW,
    )
    # make the observed-in group a seed root so lineage = depth 0
    case = await storage.create_case(
        title="operation",
        description=None,
        opened_by_user_id=UUID(int=2),
        now=_NOW,
        service="t",
        instance_id="t1",
    )
    await storage.update_case_discovery_policy(
        case_id=case.id,
        seed_root_group_ids=[root_group],
        editor_user_id=UUID(int=2),
        now=_NOW,
        service="t",
        instance_id="t1",
    )
    body = "join @target_channel and grab https://evil.example/drop"
    await storage.put_message(
        MessageTable(
            source_id=src,
            group_id=root_group,
            actor_id=actor_id,
            platform_msgid="100",
            evidence_ref="tg:rootgroup:100",
            body=body,
            length_chars=len(body),
            length_words=len(body.split()),
            sent_at_source=_NOW,
            ingested_at=_NOW,
        )
    )
    return (
        compute_instance_id("tg_alpha", SourceKind.TELEGRAM),
        "tg:rootgroup:100",
        root_group,
        src,
    )


@pytest.mark.integration
async def test_discovery_sensor_end_to_end() -> None:
    storage = get_repository(in_memory=True)
    bus = MemoryBus()
    instance_id, evidence_ref, root_group, src = await _seed(storage)

    env = RawMessageEnvelope(
        trace_context={"traceparent": "00-" + "0" * 32 + "-" + "0" * 16 + "-01"},
        source=SourceKind.TELEGRAM,
        instance_id=instance_id,
        evidence_ref=evidence_ref,
        actor_key="actor:1",
        platform_groupid="rootgroup",
        platform_msgid="100",
        sent_at_source=_NOW,
        collected_at=_NOW,
        length_chars=10,
        length_words=2,
        body_sha256="0" * 64,
    )

    sensor = DiscoverySensor(bus=bus, storage=storage)
    await sensor._dispatch(env, {})

    # channel reference recorded a candidate at depth 1 under the seed root
    cands = await storage.list_candidates(limit=10)
    assert len(cands) == 1
    assert cands[0].platform_groupid == "@target_channel"
    inputs = await storage.compute_eligibility_inputs(cands[0].id)
    assert inputs.mentions[0].depth_from_root == 1
    assert inputs.mentions[0].seed_root_id == root_group
    # candidate was scored (one group, one actor → 0.5) but no threshold → DISCOVERED
    assert cands[0].state is CandidateState.DISCOVERED
    assert cands[0].score == pytest.approx(0.5)

    # url_extraction wrote the domain artifact; Path A resolved it to the source
    artifacts = await storage.list_artifacts_for_source(src)
    assert {a.value for a in artifacts} == {"evil.example"}
    assert artifacts[0].resolution_state is ResolutionState.RESOLVED


@pytest.mark.integration
async def test_discovery_sensor_unknown_collector_skips() -> None:
    storage = get_repository(in_memory=True)
    bus = MemoryBus()
    env = RawMessageEnvelope(
        trace_context={"traceparent": "00-" + "0" * 32 + "-" + "0" * 16 + "-01"},
        source=SourceKind.TELEGRAM,
        instance_id="deadbeef",
        evidence_ref="tg:x:1",
        actor_key="actor:1",
        platform_groupid="g",
        platform_msgid="1",
        sent_at_source=_NOW,
        collected_at=_NOW,
        length_chars=1,
        length_words=1,
        body_sha256="0" * 64,
    )
    sensor = DiscoverySensor(bus=bus, storage=storage)
    await sensor._dispatch(env, {})
    # unattributable → nothing recorded
    assert await storage.list_candidates(limit=10) == []
