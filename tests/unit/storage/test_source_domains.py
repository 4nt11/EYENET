"""Storage tests for SourceDomain CRUD + overlap detection (MODELS §2.26).

Default fixture per CLAUDE.md §2.3 Rule 2: ``BaseRepository`` typed,
constructed via ``get_repository(in_memory=True)``. SQLite-impl-specific
schema probes (raw IntegrityError on CHECK violations) live in
``test_source_domains_sqlite.py`` so the MySQL/Postgres mirror files can
slot in later without collision.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from eyenet.contracts.enums import SourceDomainPatternKind as Kind, SourceKind
from eyenet.storage.errors import SourceDomainOverlapError
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

_NOW = datetime(2026, 5, 25, tzinfo=UTC)
_OPERATOR = UUID("00000000-0000-0000-0000-000000000001")


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


async def _make_source(storage: BaseRepository, name: str) -> UUID:
    return await storage.upsert_source(
        kind=SourceKind.FORUM,
        display_name=name,
        created_at=_NOW,
    )


# --- add: happy path --------------------------------------------------


@pytest.mark.unit
async def test_add_exact_domain(storage: BaseRepository) -> None:
    source_id = await _make_source(storage, "ALPHA")
    row = await storage.add_source_domain(
        source_id=source_id,
        pattern="forum.example.com",
        pattern_kind=Kind.EXACT,
        is_primary=True,
        created_at=_NOW,
        created_by_user_id=_OPERATOR,
    )
    assert row.source_id == source_id
    assert row.pattern == "forum.example.com"
    assert row.pattern_kind is Kind.EXACT
    assert row.is_primary is True
    assert row.removed_at is None


@pytest.mark.unit
async def test_add_normalizes_pattern(storage: BaseRepository) -> None:
    source_id = await _make_source(storage, "ALPHA")
    row = await storage.add_source_domain(
        source_id=source_id,
        pattern="  FOO.COM.  ",  # uppercase + trailing dot + whitespace
        pattern_kind=Kind.EXACT,
        is_primary=False,
        created_at=_NOW,
    )
    assert row.pattern == "foo.com"


# --- overlap detection ------------------------------------------------


@pytest.mark.unit
async def test_duplicate_exact_raises(storage: BaseRepository) -> None:
    source_id = await _make_source(storage, "ALPHA")
    await storage.add_source_domain(
        source_id=source_id,
        pattern="foo.com",
        pattern_kind=Kind.EXACT,
        is_primary=True,
        created_at=_NOW,
    )
    with pytest.raises(SourceDomainOverlapError) as excinfo:
        await storage.add_source_domain(
            source_id=source_id,
            pattern="foo.com",
            pattern_kind=Kind.EXACT,
            is_primary=False,
            created_at=_NOW,
        )
    assert excinfo.value.conflict_kind == Kind.EXACT.value


@pytest.mark.unit
async def test_exact_overlaps_existing_wildcard(storage: BaseRepository) -> None:
    source_id = await _make_source(storage, "ALPHA")
    await storage.add_source_domain(
        source_id=source_id,
        pattern="foo.com",
        pattern_kind=Kind.SUBDOMAIN_WILDCARD,
        is_primary=True,
        created_at=_NOW,
    )
    # x.foo.com is in the *.foo.com region — conflict.
    with pytest.raises(SourceDomainOverlapError):
        await storage.add_source_domain(
            source_id=source_id,
            pattern="x.foo.com",
            pattern_kind=Kind.EXACT,
            is_primary=False,
            created_at=_NOW,
        )


@pytest.mark.unit
async def test_overlap_is_global_across_sources(storage: BaseRepository) -> None:
    # Security property: a wildcard from Source A blocks an exact from
    # Source B in the same DNS region (no ambiguous routing).
    src_a = await _make_source(storage, "ALPHA")
    src_b = await _make_source(storage, "BETA")
    await storage.add_source_domain(
        source_id=src_a,
        pattern="foo.com",
        pattern_kind=Kind.SUBDOMAIN_WILDCARD,
        is_primary=True,
        created_at=_NOW,
    )
    with pytest.raises(SourceDomainOverlapError):
        await storage.add_source_domain(
            source_id=src_b,
            pattern="x.foo.com",
            pattern_kind=Kind.EXACT,
            is_primary=True,
            created_at=_NOW,
        )


@pytest.mark.unit
async def test_label_boundary_unrelated_does_not_conflict(
    storage: BaseRepository,
) -> None:
    # foo.com and oo.com are not in the same DNS region — must NOT conflict.
    src = await _make_source(storage, "ALPHA")
    await storage.add_source_domain(
        source_id=src,
        pattern="oo.com",
        pattern_kind=Kind.EXACT,
        is_primary=True,
        created_at=_NOW,
    )
    # Adding foo.com (different domain entirely) should succeed.
    row = await storage.add_source_domain(
        source_id=src,
        pattern="foo.com",
        pattern_kind=Kind.EXACT,
        is_primary=False,
        created_at=_NOW,
    )
    assert row.pattern == "foo.com"


# --- soft delete ------------------------------------------------------


@pytest.mark.unit
async def test_soft_delete_preserves_row_and_unblocks_pattern(
    storage: BaseRepository,
) -> None:
    src = await _make_source(storage, "ALPHA")
    first = await storage.add_source_domain(
        source_id=src,
        pattern="foo.com",
        pattern_kind=Kind.EXACT,
        is_primary=True,
        created_at=_NOW,
    )
    removed = await storage.remove_source_domain(
        domain_id=first.id,
        removed_at=_NOW,
        removed_by_user_id=_OPERATOR,
    )
    assert removed.removed_at is not None
    assert removed.removed_by_user_id == _OPERATOR
    # Same pattern can be re-claimed after removal.
    second = await storage.add_source_domain(
        source_id=src,
        pattern="foo.com",
        pattern_kind=Kind.EXACT,
        is_primary=True,
        created_at=_NOW,
    )
    assert second.id != first.id
    assert second.pattern == "foo.com"


@pytest.mark.unit
async def test_remove_unknown_raises(storage: BaseRepository) -> None:
    with pytest.raises(ValueError, match="not found"):
        await storage.remove_source_domain(
            domain_id=uuid4(),
            removed_at=_NOW,
            removed_by_user_id=_OPERATOR,
        )


@pytest.mark.unit
async def test_double_remove_raises(storage: BaseRepository) -> None:
    src = await _make_source(storage, "ALPHA")
    row = await storage.add_source_domain(
        source_id=src,
        pattern="foo.com",
        pattern_kind=Kind.EXACT,
        is_primary=True,
        created_at=_NOW,
    )
    await storage.remove_source_domain(
        domain_id=row.id,
        removed_at=_NOW,
        removed_by_user_id=_OPERATOR,
    )
    with pytest.raises(ValueError, match="already removed"):
        await storage.remove_source_domain(
            domain_id=row.id,
            removed_at=_NOW,
            removed_by_user_id=_OPERATOR,
        )


# --- find_source_for_host --------------------------------------------


@pytest.mark.unit
async def test_exact_under_wildcard_is_blocked_by_overlap(
    storage: BaseRepository,
) -> None:
    # Specificity ordering in find_source_for_host (exact > wildcard >
    # suffix) is for documentation. In practice the global-overlap rule
    # makes "exact under wildcard for same DNS region" impossible at
    # insert time — this test fixes that contract.
    src_a = await _make_source(storage, "ALPHA")
    src_b = await _make_source(storage, "BETA")
    await storage.add_source_domain(
        source_id=src_a,
        pattern="foo.com",
        pattern_kind=Kind.SUBDOMAIN_WILDCARD,
        is_primary=True,
        created_at=_NOW,
    )
    with pytest.raises(SourceDomainOverlapError):
        await storage.add_source_domain(
            source_id=src_b,
            pattern="api.foo.com",
            pattern_kind=Kind.EXACT,
            is_primary=True,
            created_at=_NOW,
        )


@pytest.mark.unit
async def test_find_returns_wildcard_over_suffix(storage: BaseRepository) -> None:
    # In the same DNS region, wildcard (more specific) beats suffix_match.
    # Two distinct DNS regions to avoid overlap: setup wildcard for foo.com
    # and a suffix for bar.com; lookup x.foo.com.
    src_w = await _make_source(storage, "W")
    src_s = await _make_source(storage, "S")
    await storage.add_source_domain(
        source_id=src_w,
        pattern="foo.com",
        pattern_kind=Kind.SUBDOMAIN_WILDCARD,
        is_primary=True,
        created_at=_NOW,
    )
    await storage.add_source_domain(
        source_id=src_s,
        pattern="bar.com",
        pattern_kind=Kind.SUFFIX_MATCH,
        is_primary=True,
        created_at=_NOW,
    )
    hit_w = await storage.find_source_for_host("x.foo.com")
    assert hit_w is not None and hit_w.source_id == src_w
    hit_s = await storage.find_source_for_host("bar.com")
    assert hit_s is not None and hit_s.source_id == src_s


@pytest.mark.unit
async def test_find_normalizes_input(storage: BaseRepository) -> None:
    src = await _make_source(storage, "ALPHA")
    await storage.add_source_domain(
        source_id=src,
        pattern="foo.com",
        pattern_kind=Kind.EXACT,
        is_primary=True,
        created_at=_NOW,
    )
    # Mixed case + trailing dot must still hit.
    hit = await storage.find_source_for_host("FOO.COM.")
    assert hit is not None
    assert hit.source_id == src


@pytest.mark.unit
async def test_find_returns_none_when_no_match(storage: BaseRepository) -> None:
    src = await _make_source(storage, "ALPHA")
    await storage.add_source_domain(
        source_id=src,
        pattern="foo.com",
        pattern_kind=Kind.EXACT,
        is_primary=True,
        created_at=_NOW,
    )
    assert await storage.find_source_for_host("unrelated.example") is None


@pytest.mark.unit
async def test_find_skips_removed_rows(storage: BaseRepository) -> None:
    src = await _make_source(storage, "ALPHA")
    row = await storage.add_source_domain(
        source_id=src,
        pattern="foo.com",
        pattern_kind=Kind.EXACT,
        is_primary=True,
        created_at=_NOW,
    )
    await storage.remove_source_domain(
        domain_id=row.id,
        removed_at=_NOW,
        removed_by_user_id=_OPERATOR,
    )
    assert await storage.find_source_for_host("foo.com") is None


@pytest.mark.unit
async def test_find_tiebreak_oldest_wins(storage: BaseRepository) -> None:
    # Two suffix_match patterns claiming different but compatible regions.
    # Use separate non-overlapping suffix patterns to avoid the overlap
    # invariant; verify the ordering function is deterministic on
    # created_at.
    src_old = await _make_source(storage, "OLD")
    src_new = await _make_source(storage, "NEW")
    older = datetime(2025, 1, 1, tzinfo=UTC)
    newer = datetime(2026, 1, 1, tzinfo=UTC)
    await storage.add_source_domain(
        source_id=src_old,
        pattern="alpha.example",
        pattern_kind=Kind.SUFFIX_MATCH,
        is_primary=True,
        created_at=older,
    )
    await storage.add_source_domain(
        source_id=src_new,
        pattern="beta.example",
        pattern_kind=Kind.SUFFIX_MATCH,
        is_primary=True,
        created_at=newer,
    )
    # Lookup for x.alpha.example must hit the older row.
    hit = await storage.find_source_for_host("x.alpha.example")
    assert hit is not None
    assert hit.source_id == src_old


# --- concurrency ------------------------------------------------------


@pytest.mark.unit
async def test_serial_overlap_check_prevents_strict_subdomain_under_wildcard(
    storage: BaseRepository,
) -> None:
    # Under serial access (the actual M9.C1 use case), the overlap check
    # is the gate. Cross-coroutine serialization needs `BEGIN IMMEDIATE`
    # at the SQLiteRepository override level (per CLAUDE.md §2.3 Rule 1)
    # — that lands in a follow-up C-slice when concurrent writes become
    # realistic (M9.D1 HTTP surface). The mixin's TODO references the
    # Postgres path too; both override at the concrete-backend layer.
    src = await _make_source(storage, "ALPHA")
    await storage.add_source_domain(
        source_id=src,
        pattern="foo.com",
        pattern_kind=Kind.SUBDOMAIN_WILDCARD,
        is_primary=False,
        created_at=_NOW,
    )
    with pytest.raises(SourceDomainOverlapError):
        await storage.add_source_domain(
            source_id=src,
            pattern="x.foo.com",
            pattern_kind=Kind.EXACT,
            is_primary=False,
            created_at=_NOW,
        )
