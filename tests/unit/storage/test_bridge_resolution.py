"""Storage tests for §2.25 bridge resolution + GroupAccessArtifact (M9.C6).

DoD coverage:
- Path A: artifact INSERT against an existing SourceDomain → immediately RESOLVED
- Path B: SourceDomain INSERT after unresolved artifacts → retroactively RESOLVED
- Both verified under asyncio.gather concurrency
- Non-bridgeable kinds → NOT_APPLICABLE
- GroupAccessArtifact CRUD round-trip
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from eyenet.contracts.access_artifact import GroupAccessArtifactRow
from eyenet.contracts.enums import (
    ArtifactSubjectKind,
    ArtifactValidationState,
    GroupAccessKind,
    GroupKind,
    InfrastructureKind,
    MentionKind,
    ResolutionState,
    SourceDomainPatternKind,
    SourceKind,
)
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

_NOW = datetime(2026, 5, 25, tzinfo=UTC)


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


async def _make_source(storage: BaseRepository, name: str) -> UUID:
    return await storage.upsert_source(
        kind=SourceKind.FORUM,
        display_name=f"forum:{name}",
        created_at=_NOW,
    )


async def _add_domain(
    storage: BaseRepository,
    source_id: UUID,
    pattern: str,
    *,
    primary: bool = True,
    kind: SourceDomainPatternKind = SourceDomainPatternKind.EXACT,
) -> UUID:
    row = await storage.add_source_domain(
        source_id=source_id,
        pattern=pattern,
        pattern_kind=kind,
        is_primary=primary,
        created_at=_NOW,
    )
    return row.id


# --- Path A: artifact INSERT against existing SourceDomain --------------


@pytest.mark.unit
async def test_path_a_artifact_insert_resolves_to_existing_source(
    storage: BaseRepository,
) -> None:
    src = await _make_source(storage, "alpha")
    await _add_domain(storage, src, "forum.example.com")

    art = await storage.put_infrastructure_artifact(
        kind=InfrastructureKind.DOMAIN,
        value="forum.example.com",
        first_seen_at_ingest=_NOW,
        last_seen_at_ingest=_NOW,
    )
    assert art.resolution_state is ResolutionState.RESOLVED
    assert art.resolved_to_source_id == src


@pytest.mark.unit
async def test_path_a_paste_url_extracts_host(storage: BaseRepository) -> None:
    src = await _make_source(storage, "alpha")
    await _add_domain(storage, src, "pastebin.example.com")

    art = await storage.put_infrastructure_artifact(
        kind=InfrastructureKind.PASTE_URL,
        value="https://pastebin.example.com/raw/aBcD1234",
        first_seen_at_ingest=_NOW,
        last_seen_at_ingest=_NOW,
    )
    assert art.resolution_state is ResolutionState.RESOLVED
    assert art.resolved_to_source_id == src


@pytest.mark.unit
async def test_path_a_no_match_stays_unresolved(storage: BaseRepository) -> None:
    art = await storage.put_infrastructure_artifact(
        kind=InfrastructureKind.DOMAIN,
        value="unknown.example.org",
        first_seen_at_ingest=_NOW,
        last_seen_at_ingest=_NOW,
    )
    assert art.resolution_state is ResolutionState.UNRESOLVED
    assert art.resolved_to_source_id is None


@pytest.mark.unit
async def test_path_a_wildcard_match(storage: BaseRepository) -> None:
    src = await _make_source(storage, "alpha")
    await _add_domain(
        storage,
        src,
        "example.com",
        kind=SourceDomainPatternKind.SUBDOMAIN_WILDCARD,
    )

    art = await storage.put_infrastructure_artifact(
        kind=InfrastructureKind.DOMAIN,
        value="foo.example.com",
        first_seen_at_ingest=_NOW,
        last_seen_at_ingest=_NOW,
    )
    assert art.resolution_state is ResolutionState.RESOLVED
    assert art.resolved_to_source_id == src


# --- Non-bridgeable kinds → NOT_APPLICABLE ------------------------------


@pytest.mark.unit
async def test_wallet_kind_is_not_applicable(storage: BaseRepository) -> None:
    art = await storage.put_infrastructure_artifact(
        kind=InfrastructureKind.WALLET_BTC,
        value="bc1q9d4ywgfnd8h43da5tpcxcn6ajv590cg6d3tg6axemvljvt2k76zs50tv4q",
        first_seen_at_ingest=_NOW,
        last_seen_at_ingest=_NOW,
    )
    assert art.resolution_state is ResolutionState.NOT_APPLICABLE
    assert art.resolved_to_source_id is None


@pytest.mark.unit
async def test_email_kind_is_not_applicable(storage: BaseRepository) -> None:
    art = await storage.put_infrastructure_artifact(
        kind=InfrastructureKind.EMAIL,
        value="abuse@example.com",
        first_seen_at_ingest=_NOW,
        last_seen_at_ingest=_NOW,
    )
    assert art.resolution_state is ResolutionState.NOT_APPLICABLE


# --- Path B: SourceDomain INSERT resolves prior unresolved artifacts ----


@pytest.mark.unit
async def test_path_b_source_domain_resolves_prior_unresolved(
    storage: BaseRepository,
) -> None:
    # Artifact arrives BEFORE Source/SourceDomain — stays unresolved.
    art = await storage.put_infrastructure_artifact(
        kind=InfrastructureKind.DOMAIN,
        value="late-forum.example.net",
        first_seen_at_ingest=_NOW,
        last_seen_at_ingest=_NOW,
    )
    assert art.resolution_state is ResolutionState.UNRESOLVED

    # Operator later configures the Source + adds the matching SourceDomain.
    src = await _make_source(storage, "late")
    await _add_domain(storage, src, "late-forum.example.net")

    # Path B should have flipped the prior artifact to RESOLVED inline.
    fetched = await storage.get_infrastructure_artifact(art.id)
    assert fetched is not None
    assert fetched.resolution_state is ResolutionState.RESOLVED
    assert fetched.resolved_to_source_id == src


@pytest.mark.unit
async def test_path_b_does_not_touch_non_matching_artifacts(
    storage: BaseRepository,
) -> None:
    other = await storage.put_infrastructure_artifact(
        kind=InfrastructureKind.DOMAIN,
        value="other-host.example.net",
        first_seen_at_ingest=_NOW,
        last_seen_at_ingest=_NOW,
    )
    src = await _make_source(storage, "alpha")
    await _add_domain(storage, src, "matched-host.example.net")

    fetched = await storage.get_infrastructure_artifact(other.id)
    assert fetched is not None
    assert fetched.resolution_state is ResolutionState.UNRESOLVED
    assert fetched.resolved_to_source_id is None


@pytest.mark.unit
async def test_path_b_does_not_touch_not_applicable(storage: BaseRepository) -> None:
    wallet = await storage.put_infrastructure_artifact(
        kind=InfrastructureKind.WALLET_ETH,
        value="0x0000000000000000000000000000000000000000",
        first_seen_at_ingest=_NOW,
        last_seen_at_ingest=_NOW,
    )
    src = await _make_source(storage, "alpha")
    await _add_domain(storage, src, "0x0000000000000000000000000000000000000000")
    # Adding a domain whose pattern accidentally matches the wallet text
    # must not flip a NOT_APPLICABLE artifact.

    fetched = await storage.get_infrastructure_artifact(wallet.id)
    assert fetched is not None
    assert fetched.resolution_state is ResolutionState.NOT_APPLICABLE


# --- list_artifacts_for_source -----------------------------------------


@pytest.mark.unit
async def test_list_artifacts_for_source(storage: BaseRepository) -> None:
    src = await _make_source(storage, "alpha")
    await _add_domain(storage, src, "alpha.example.com")

    art_a = await storage.put_infrastructure_artifact(
        kind=InfrastructureKind.DOMAIN,
        value="alpha.example.com",
        first_seen_at_ingest=_NOW,
        last_seen_at_ingest=_NOW,
    )
    # Unrelated artifact — should NOT appear in the list.
    await storage.put_infrastructure_artifact(
        kind=InfrastructureKind.DOMAIN,
        value="zeta.example.org",
        first_seen_at_ingest=_NOW,
        last_seen_at_ingest=_NOW,
    )

    listed = await storage.list_artifacts_for_source(src)
    assert len(listed) == 1
    assert listed[0].id == art_a.id


# --- asyncio.gather concurrency ----------------------------------------


@pytest.mark.unit
async def test_path_a_concurrent_artifact_inserts_resolve(
    storage: BaseRepository,
) -> None:
    # Both Path A inserts happen concurrently against the same existing
    # SourceDomain — both must resolve.
    src = await _make_source(storage, "alpha")
    await _add_domain(storage, src, "concurrent.example.com")

    a, b = await asyncio.gather(
        storage.put_infrastructure_artifact(
            kind=InfrastructureKind.DOMAIN,
            value="concurrent.example.com",
            first_seen_at_ingest=_NOW,
            last_seen_at_ingest=_NOW,
        ),
        storage.put_infrastructure_artifact(
            kind=InfrastructureKind.PASTE_URL,
            value="https://concurrent.example.com/paste/x",
            first_seen_at_ingest=_NOW,
            last_seen_at_ingest=_NOW,
        ),
    )
    assert a.resolution_state is ResolutionState.RESOLVED
    assert b.resolution_state is ResolutionState.RESOLVED
    assert a.resolved_to_source_id == src
    assert b.resolved_to_source_id == src


# --- idempotency on value_hash -----------------------------------------


@pytest.mark.unit
async def test_put_artifact_idempotent_on_value_hash(storage: BaseRepository) -> None:
    later = datetime(2026, 6, 1, tzinfo=UTC)

    first = await storage.put_infrastructure_artifact(
        kind=InfrastructureKind.DOMAIN,
        value="dup.example.com",
        first_seen_at_ingest=_NOW,
        last_seen_at_ingest=_NOW,
    )
    second = await storage.put_infrastructure_artifact(
        kind=InfrastructureKind.DOMAIN,
        value="dup.example.com",
        first_seen_at_ingest=later,
        last_seen_at_ingest=later,
    )
    assert second.id == first.id
    assert second.last_seen_at_ingest == later


# --- GroupAccessArtifact CRUD ------------------------------------------


@pytest.mark.unit
async def test_add_group_access_artifact_for_group(storage: BaseRepository) -> None:
    src = await _make_source(storage, "alpha")
    group_id = await storage.upsert_group(
        source_id=src,
        platform_groupid="grp_a",
        kind=GroupKind.CHANNEL,
        title="grp_a",
        seen_at=_NOW,
    )
    row = await storage.add_group_access_artifact(
        subject_kind=ArtifactSubjectKind.GROUP,
        group_id=group_id,
        candidate_id=None,
        kind=GroupAccessKind.PUBLIC_IDENTIFIER,
        value="@rutify",
        discovered_at_ingest=_NOW,
        validation_state=ArtifactValidationState.VALID,
    )
    assert isinstance(row, GroupAccessArtifactRow)
    assert row.subject_kind is ArtifactSubjectKind.GROUP
    assert row.group_id == group_id
    assert row.candidate_id is None
    assert row.kind is GroupAccessKind.PUBLIC_IDENTIFIER
    assert row.value == "@rutify"
    assert row.validation_state is ArtifactValidationState.VALID


# --- M9.E5.5: getter / list-for-candidate / validation-state writeback ---

_FAKE_COLLECTOR_E55 = UUID("00000000-0000-0000-0000-0000000000e5")


async def _candidate_for_artifacts(storage: BaseRepository, name: str) -> UUID:
    """Create a GroupCandidate (via a mention) to hang access artifacts off of."""
    src = await _make_source(storage, name)
    group_id = await storage.upsert_group(
        source_id=src,
        platform_groupid=f"observed_{name}",
        kind=GroupKind.CHANNEL,
        title=f"observed_{name}",
        seen_at=_NOW,
    )
    actor = await storage.upsert_actor(
        source_id=src,
        actor_key=f"actor:{'a' * 60}{name[:4]}",
        platform_userid=f"u_{name}",
        handle=None,
        display_name=None,
        seen_at=_NOW,
    )
    candidate, _mention = await storage.record_candidate_mention(
        source_id=src,
        platform_groupid=f"cand_{name}",
        observed_by_collector_id=_FAKE_COLLECTOR_E55,
        observed_in_group_id=group_id,
        seed_root_id=None,
        depth_from_root=1,
        mention_evidence_ref=f"telegram:-100000:{name}",
        mention_kind=MentionKind.INVITE_LINK,
        mentioned_at_source=_NOW,
        mentioned_at_ingest=_NOW,
        mentioning_actor_id=actor,
    )
    return candidate.id


@pytest.mark.unit
async def test_get_group_access_artifact_round_trips(storage: BaseRepository) -> None:
    cand = await _candidate_for_artifacts(storage, "getter")
    created = await storage.add_group_access_artifact(
        subject_kind=ArtifactSubjectKind.CANDIDATE,
        group_id=None,
        candidate_id=cand,
        kind=GroupAccessKind.INVITE_LINK,
        value="https://t.me/+abc123",
        discovered_at_ingest=_NOW,
    )
    fetched = await storage.get_group_access_artifact(created.id)
    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.candidate_id == cand
    assert fetched.kind is GroupAccessKind.INVITE_LINK
    assert fetched.value == "https://t.me/+abc123"


@pytest.mark.unit
async def test_get_group_access_artifact_missing_returns_none(
    storage: BaseRepository,
) -> None:
    assert await storage.get_group_access_artifact(uuid4()) is None


@pytest.mark.unit
async def test_list_group_access_artifacts_for_candidate_filters_by_subject(
    storage: BaseRepository,
) -> None:
    cand = await _candidate_for_artifacts(storage, "lister")
    other = await _candidate_for_artifacts(storage, "other")
    a1 = await storage.add_group_access_artifact(
        subject_kind=ArtifactSubjectKind.CANDIDATE,
        group_id=None,
        candidate_id=cand,
        kind=GroupAccessKind.INVITE_LINK,
        value="https://t.me/+one",
        discovered_at_ingest=_NOW,
    )
    a2 = await storage.add_group_access_artifact(
        subject_kind=ArtifactSubjectKind.CANDIDATE,
        group_id=None,
        candidate_id=cand,
        kind=GroupAccessKind.PUBLIC_IDENTIFIER,
        value="@two",
        discovered_at_ingest=_NOW,
    )
    # An artifact on a different candidate must NOT leak into the list.
    await storage.add_group_access_artifact(
        subject_kind=ArtifactSubjectKind.CANDIDATE,
        group_id=None,
        candidate_id=other,
        kind=GroupAccessKind.INVITE_LINK,
        value="https://t.me/+three",
        discovered_at_ingest=_NOW,
    )
    rows = await storage.list_group_access_artifacts_for_candidate(cand)
    assert {r.id for r in rows} == {a1.id, a2.id}
    assert all(r.candidate_id == cand for r in rows)


@pytest.mark.unit
async def test_set_artifact_validation_state_writes_back(storage: BaseRepository) -> None:
    cand = await _candidate_for_artifacts(storage, "writeback")
    created = await storage.add_group_access_artifact(
        subject_kind=ArtifactSubjectKind.CANDIDATE,
        group_id=None,
        candidate_id=cand,
        kind=GroupAccessKind.INVITE_LINK,
        value="https://t.me/+dead",
        discovered_at_ingest=_NOW,
    )
    assert created.validation_state is ArtifactValidationState.UNVERIFIED
    validated_at = datetime(2026, 5, 26, tzinfo=UTC)
    updated = await storage.set_artifact_validation_state(
        artifact_id=created.id,
        validation_state=ArtifactValidationState.EXPIRED,
        last_validated_at=validated_at,
    )
    assert updated is not None
    assert updated.validation_state is ArtifactValidationState.EXPIRED
    assert updated.last_validated_at == validated_at
    # Durable: a fresh read sees the new state.
    refetched = await storage.get_group_access_artifact(created.id)
    assert refetched is not None
    assert refetched.validation_state is ArtifactValidationState.EXPIRED


@pytest.mark.unit
async def test_set_artifact_validation_state_missing_returns_none(
    storage: BaseRepository,
) -> None:
    result = await storage.set_artifact_validation_state(
        artifact_id=uuid4(),
        validation_state=ArtifactValidationState.REVOKED,
        last_validated_at=_NOW,
    )
    assert result is None
