"""Tests for the `channel_reference_extraction` discovery extractor (M9.E2).

DoD coverage:
- mention upsert is idempotent (redelivery records no duplicate)
- depth_from_root propagated as observed-group depth + 1
- Telegram invite/public/@handle + Matrix alias forms detected
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from eyenet.contracts.enums import CandidateState, SourceKind
from eyenet.sensor.discovery import (
    DISCOVERY_EXTRACTORS,
    ChannelReferenceExtractor,
    MessageContext,
)
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

_NOW = datetime(2026, 6, 5, tzinfo=UTC)
_COLLECTOR = UUID("00000000-0000-0000-0000-0000000000c1")
_ACTOR = UUID("00000000-0000-0000-0000-0000000000a1")


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


async def _source(storage: BaseRepository) -> UUID:
    return await storage.upsert_source(
        kind=SourceKind.TELEGRAM, display_name="telegram:s", created_at=_NOW
    )


def _ctx(
    text: str,
    *,
    source_id: UUID,
    observed_in: UUID,
    seed_root: UUID | None,
    depth: int,
    evidence: str = "tg:100:200",
) -> MessageContext:
    return MessageContext(
        text=text,
        source_id=source_id,
        observed_by_collector_id=_COLLECTOR,
        observed_in_group_id=observed_in,
        seed_root_id=seed_root,
        depth_from_root=depth,
        mentioning_actor_id=_ACTOR,
        evidence_ref=evidence,
        sent_at_source=_NOW,
        collected_at=_NOW,
    )


@pytest.mark.unit
async def test_registered() -> None:
    assert any(isinstance(e, ChannelReferenceExtractor) for e in DISCOVERY_EXTRACTORS)
    assert ChannelReferenceExtractor.name == "channel_reference_extraction"


@pytest.mark.unit
async def test_detects_multiple_forms(storage: BaseRepository) -> None:
    src = await _source(storage)
    text = (
        "join https://t.me/+AbCdEfGhIjKl now, mirror @backup_channel, "
        "public t.me/openchat, matrix #ops:example.org"
    )
    n = await ChannelReferenceExtractor().process(
        _ctx(text, source_id=src, observed_in=uuid4(), seed_root=uuid4(), depth=0), storage
    )
    # invite hash + @backup_channel + @openchat + #ops:example.org = 4
    assert n == 4


@pytest.mark.unit
async def test_depth_propagation(storage: BaseRepository) -> None:
    src = await _source(storage)
    root = uuid4()
    observed = uuid4()
    await ChannelReferenceExtractor().process(
        _ctx("see @child_chan", source_id=src, observed_in=observed, seed_root=root, depth=2),
        storage,
    )
    # the candidate the mention created
    cands = await storage.list_candidates(state=CandidateState.DISCOVERED, limit=10)
    assert len(cands) == 1
    inputs = await storage.compute_eligibility_inputs(cands[0].id)
    assert inputs.mentions[0].depth_from_root == 3  # observed depth 2 + 1
    assert inputs.mentions[0].seed_root_id == root


@pytest.mark.unit
async def test_idempotent_on_redelivery(storage: BaseRepository) -> None:
    src = await _source(storage)
    ctx = _ctx("ping @dup_chan", source_id=src, observed_in=uuid4(), seed_root=None, depth=0)
    first = await ChannelReferenceExtractor().process(ctx, storage)
    second = await ChannelReferenceExtractor().process(ctx, storage)
    assert first == 1
    assert second == 1  # re-processed, but...
    # ...only one candidate + one mention exist
    cands = await storage.list_candidates(limit=10)
    assert len(cands) == 1
    inputs = await storage.compute_eligibility_inputs(cands[0].id)
    assert len(inputs.mentions) == 1


@pytest.mark.unit
async def test_no_references_records_nothing(storage: BaseRepository) -> None:
    src = await _source(storage)
    n = await ChannelReferenceExtractor().process(
        _ctx(
            "just talking, no links here",
            source_id=src,
            observed_in=uuid4(),
            seed_root=None,
            depth=0,
        ),
        storage,
    )
    assert n == 0
    assert await storage.list_candidates(limit=10) == []
