"""Tests for the `url_extraction` discovery extractor (M9.E1).

DoD coverage:
- unicode ↔ punycode duplicates collapse to one artifact
- resolved + unresolved Path-A branches both exercised
- onion hosts classified ONION, invalid hosts skipped
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from eyenet.contracts.enums import (
    InfrastructureKind,
    ResolutionState,
    SourceDomainPatternKind,
    SourceKind,
)
from eyenet.sensor.discovery import DISCOVERY_EXTRACTORS, MessageContext, UrlExtractor
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

_NOW = datetime(2026, 6, 5, tzinfo=UTC)


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


def _ctx(text: str) -> MessageContext:
    return MessageContext(
        text=text,
        source_id=uuid4(),
        observed_by_collector_id=uuid4(),
        observed_in_group_id=uuid4(),
        seed_root_id=None,
        depth_from_root=0,
        mentioning_actor_id=uuid4(),
        evidence_ref="tg:1:1",
        sent_at_source=_NOW,
        collected_at=_NOW,
    )


@pytest.mark.unit
async def test_extractor_registered() -> None:
    assert any(isinstance(e, UrlExtractor) for e in DISCOVERY_EXTRACTORS)
    assert UrlExtractor.name == "url_extraction"


@pytest.mark.unit
async def test_punycode_and_unicode_collapse(storage: BaseRepository) -> None:
    # Both forms of the same host must reduce to ONE artifact.
    text = "see https://münchen.de/a and http://xn--mnchen-3ya.de/b"
    written = await UrlExtractor().process(_ctx(text), storage)
    assert written == 1


@pytest.mark.unit
async def test_resolved_and_unresolved_branches(storage: BaseRepository) -> None:
    src = await storage.upsert_source(
        kind=SourceKind.TELEGRAM, display_name="telegram:s", created_at=_NOW
    )
    await storage.add_source_domain(
        source_id=src,
        pattern="known.example",
        pattern_kind=SourceDomainPatternKind.EXACT,
        is_primary=True,
        created_at=_NOW,
    )
    text = "mirror at https://known.example/x or https://unknown.test/y"
    written = await UrlExtractor().process(_ctx(text), storage)
    assert written == 2

    # known.example resolved to the source (Path A ran inline)
    resolved = await storage.list_artifacts_for_source(src)
    assert {a.value for a in resolved} == {"known.example"}
    assert all(a.resolution_state is ResolutionState.RESOLVED for a in resolved)

    # unknown.test stayed UNRESOLVED — read it back via the idempotent upsert
    again = await storage.put_infrastructure_artifact(
        kind=InfrastructureKind.DOMAIN,
        value="unknown.test",
        first_seen_at_ingest=_NOW,
        last_seen_at_ingest=_NOW,
    )
    assert again.resolution_state is ResolutionState.UNRESOLVED
    assert again.resolved_to_source_id is None


@pytest.mark.unit
async def test_onion_classified(storage: BaseRepository) -> None:
    # a v3 onion (56 base32 chars)
    onion = "a" * 56 + ".onion"
    written = await UrlExtractor().process(_ctx(f"drop {onion} now"), storage)
    assert written == 1
    again = await storage.put_infrastructure_artifact(
        kind=InfrastructureKind.ONION,
        value=onion,
        first_seen_at_ingest=_NOW,
        last_seen_at_ingest=_NOW,
    )
    assert again.kind is InfrastructureKind.ONION


@pytest.mark.unit
async def test_no_urls_writes_nothing(storage: BaseRepository) -> None:
    assert await UrlExtractor().process(_ctx("just plain chatter, no links"), storage) == 0


@pytest.mark.unit
async def test_duplicate_host_across_urls_collapses(storage: BaseRepository) -> None:
    text = "https://dup.example/a https://dup.example/b https://DUP.example/c"
    assert await UrlExtractor().process(_ctx(text), storage) == 1
