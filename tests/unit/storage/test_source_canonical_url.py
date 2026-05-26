"""Storage tests for ``set_source_canonical_url`` (M9.C2, MODELS §1.1)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from eyenet.contracts.enums import SourceDomainPatternKind as Kind, SourceKind
from eyenet.storage.errors import SourceCanonicalUrlError
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


# --- happy paths -----------------------------------------------------


@pytest.mark.unit
async def test_set_canonical_url_matching_exact_primary(
    storage: BaseRepository,
) -> None:
    source_id = await _make_source(storage, "ALPHA")
    await storage.add_source_domain(
        source_id=source_id,
        pattern="forum.example.com",
        pattern_kind=Kind.EXACT,
        is_primary=True,
        created_at=_NOW,
    )
    row = await storage.set_source_canonical_url(
        source_id=source_id,
        canonical_url="https://forum.example.com/threads",
    )
    assert row.canonical_url == "https://forum.example.com/threads"


@pytest.mark.unit
async def test_set_canonical_url_matching_wildcard_primary(
    storage: BaseRepository,
) -> None:
    source_id = await _make_source(storage, "ALPHA")
    await storage.add_source_domain(
        source_id=source_id,
        pattern="example.com",
        pattern_kind=Kind.SUBDOMAIN_WILDCARD,
        is_primary=True,
        created_at=_NOW,
    )
    # api.example.com is a strict subdomain → falls under the wildcard.
    row = await storage.set_source_canonical_url(
        source_id=source_id,
        canonical_url="https://api.example.com/v1",
    )
    assert row.canonical_url == "https://api.example.com/v1"


@pytest.mark.unit
async def test_set_canonical_url_matching_suffix_primary_at_apex(
    storage: BaseRepository,
) -> None:
    source_id = await _make_source(storage, "ALPHA")
    await storage.add_source_domain(
        source_id=source_id,
        pattern="example.com",
        pattern_kind=Kind.SUFFIX_MATCH,
        is_primary=True,
        created_at=_NOW,
    )
    # suffix_match matches the apex AND subdomains.
    row = await storage.set_source_canonical_url(
        source_id=source_id,
        canonical_url="https://example.com",
    )
    assert row.canonical_url == "https://example.com"


@pytest.mark.unit
async def test_set_canonical_url_to_none_clears(storage: BaseRepository) -> None:
    source_id = await _make_source(storage, "ALPHA")
    await storage.add_source_domain(
        source_id=source_id,
        pattern="forum.example.com",
        pattern_kind=Kind.EXACT,
        is_primary=True,
        created_at=_NOW,
    )
    await storage.set_source_canonical_url(
        source_id=source_id,
        canonical_url="https://forum.example.com/",
    )
    cleared = await storage.set_source_canonical_url(
        source_id=source_id,
        canonical_url=None,
    )
    assert cleared.canonical_url is None


@pytest.mark.unit
async def test_clear_canonical_url_when_no_primary_succeeds(
    storage: BaseRepository,
) -> None:
    # Clearing should ALWAYS work — no primary needed.
    source_id = await _make_source(storage, "ALPHA")
    row = await storage.set_source_canonical_url(
        source_id=source_id,
        canonical_url=None,
    )
    assert row.canonical_url is None


@pytest.mark.unit
async def test_set_canonical_url_normalizes_idn_host(
    storage: BaseRepository,
) -> None:
    source_id = await _make_source(storage, "ALPHA")
    # Primary domain is stored as punycode (post-normalize_host).
    await storage.add_source_domain(
        source_id=source_id,
        pattern="über.example",
        pattern_kind=Kind.EXACT,
        is_primary=True,
        created_at=_NOW,
    )
    # Operator types the URL with the unicode form — validator must
    # normalize the host before comparison.
    row = await storage.set_source_canonical_url(
        source_id=source_id,
        canonical_url="https://über.example/path",
    )
    # canonical_url is stored verbatim (display field); the host
    # equivalence is only checked at write time.
    assert row.canonical_url == "https://über.example/path"


# --- rejection paths -------------------------------------------------


@pytest.mark.unit
async def test_set_canonical_url_no_primary_raises(
    storage: BaseRepository,
) -> None:
    source_id = await _make_source(storage, "ALPHA")
    # NO SourceDomain added → no primary → reject any non-None canonical_url.
    with pytest.raises(SourceCanonicalUrlError) as excinfo:
        await storage.set_source_canonical_url(
            source_id=source_id,
            canonical_url="https://example.com",
        )
    assert excinfo.value.reason == "no_primary_domain"
    assert excinfo.value.source_id == source_id


@pytest.mark.unit
async def test_set_canonical_url_only_non_primary_domains_raises(
    storage: BaseRepository,
) -> None:
    source_id = await _make_source(storage, "ALPHA")
    # Non-primary domain only — set_source_canonical_url must still reject.
    await storage.add_source_domain(
        source_id=source_id,
        pattern="forum.example.com",
        pattern_kind=Kind.EXACT,
        is_primary=False,
        created_at=_NOW,
    )
    with pytest.raises(SourceCanonicalUrlError) as excinfo:
        await storage.set_source_canonical_url(
            source_id=source_id,
            canonical_url="https://forum.example.com",
        )
    assert excinfo.value.reason == "no_primary_domain"


@pytest.mark.unit
async def test_set_canonical_url_host_not_owned_raises(
    storage: BaseRepository,
) -> None:
    source_id = await _make_source(storage, "ALPHA")
    await storage.add_source_domain(
        source_id=source_id,
        pattern="forum.example.com",
        pattern_kind=Kind.EXACT,
        is_primary=True,
        created_at=_NOW,
    )
    # URL host is "other.example.com" — does NOT match exact "forum.example.com".
    with pytest.raises(SourceCanonicalUrlError) as excinfo:
        await storage.set_source_canonical_url(
            source_id=source_id,
            canonical_url="https://other.example.com",
        )
    assert excinfo.value.reason == "host_not_owned"


@pytest.mark.unit
async def test_set_canonical_url_apex_under_wildcard_only_raises(
    storage: BaseRepository,
) -> None:
    # subdomain_wildcard does NOT match the apex — operator using
    # https://example.com under a wildcard primary must be rejected.
    source_id = await _make_source(storage, "ALPHA")
    await storage.add_source_domain(
        source_id=source_id,
        pattern="example.com",
        pattern_kind=Kind.SUBDOMAIN_WILDCARD,
        is_primary=True,
        created_at=_NOW,
    )
    with pytest.raises(SourceCanonicalUrlError) as excinfo:
        await storage.set_source_canonical_url(
            source_id=source_id,
            canonical_url="https://example.com",
        )
    assert excinfo.value.reason == "host_not_owned"


@pytest.mark.unit
async def test_set_canonical_url_unparseable_raises(
    storage: BaseRepository,
) -> None:
    source_id = await _make_source(storage, "ALPHA")
    await storage.add_source_domain(
        source_id=source_id,
        pattern="forum.example.com",
        pattern_kind=Kind.EXACT,
        is_primary=True,
        created_at=_NOW,
    )
    # No scheme + no host → urlparse returns hostname=None.
    with pytest.raises(SourceCanonicalUrlError) as excinfo:
        await storage.set_source_canonical_url(
            source_id=source_id,
            canonical_url="not a url at all",
        )
    assert excinfo.value.reason == "invalid_url"


@pytest.mark.unit
async def test_set_canonical_url_empty_string_raises(
    storage: BaseRepository,
) -> None:
    source_id = await _make_source(storage, "ALPHA")
    with pytest.raises(SourceCanonicalUrlError) as excinfo:
        await storage.set_source_canonical_url(
            source_id=source_id,
            canonical_url="",
        )
    assert excinfo.value.reason == "invalid_url"


@pytest.mark.unit
async def test_set_canonical_url_no_host_raises(
    storage: BaseRepository,
) -> None:
    source_id = await _make_source(storage, "ALPHA")
    # file:/// has no host.
    with pytest.raises(SourceCanonicalUrlError) as excinfo:
        await storage.set_source_canonical_url(
            source_id=source_id,
            canonical_url="file:///tmp/foo",
        )
    assert excinfo.value.reason == "invalid_url"


@pytest.mark.unit
async def test_set_canonical_url_unknown_source_raises(
    storage: BaseRepository,
) -> None:
    with pytest.raises(SourceCanonicalUrlError) as excinfo:
        await storage.set_source_canonical_url(
            source_id=_OPERATOR,
            canonical_url=None,
        )
    assert excinfo.value.reason == "source_not_found"


# --- cross-source isolation -----------------------------------------


@pytest.mark.unit
async def test_set_canonical_url_does_not_consult_other_sources_primary(
    storage: BaseRepository,
) -> None:
    # Source A has a primary for "alpha.example"; Source B has none.
    # B must NOT be able to claim canonical_url under A's primary.
    src_a = await _make_source(storage, "ALPHA")
    src_b = await _make_source(storage, "BETA")
    await storage.add_source_domain(
        source_id=src_a,
        pattern="alpha.example",
        pattern_kind=Kind.EXACT,
        is_primary=True,
        created_at=_NOW,
    )
    with pytest.raises(SourceCanonicalUrlError) as excinfo:
        await storage.set_source_canonical_url(
            source_id=src_b,
            canonical_url="https://alpha.example",
        )
    assert excinfo.value.reason == "no_primary_domain"
