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
from eyenet.sensor.discovery.url_extraction import _extract, _find_bare_domains, _find_ips
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
    # the host collapses to ONE domain; the two distinct full URLs are their own artifacts
    assert written == 3


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
    assert written == 4  # 2 domains + 2 full-URL artifacts

    # known.example AND its full URL both resolve to the source (URL is bridgeable:
    # Path A resolves on the URL's host too).
    resolved = await storage.list_artifacts_for_source(src)
    assert {a.value for a in resolved} == {"known.example", "https://known.example/x"}
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
    assert again.kind == InfrastructureKind.ONION


@pytest.mark.unit
async def test_no_urls_writes_nothing(storage: BaseRepository) -> None:
    assert await UrlExtractor().process(_ctx("just plain chatter, no links"), storage) == 0


@pytest.mark.unit
async def test_duplicate_host_across_urls_collapses(storage: BaseRepository) -> None:
    text = "https://dup.example/a https://dup.example/b https://DUP.example/c"
    # the host collapses to ONE domain; /a /b /c are three distinct full URLs
    assert await UrlExtractor().process(_ctx(text), storage) == 4


# --- coded extractors: IPs (regex + ipaddress) and bare domains (tldextract) ---


@pytest.mark.unit
def test_ipv4_keeps_global_and_nonglobal_drops_unspecified() -> None:
    # Private/loopback are kept (victim-network evidence); 0.0.0.0 is "no address".
    found = _find_ips("c2 8.8.8.8 lan 192.168.12.4 loop 127.0.0.1 bind 0.0.0.0")
    assert found == {
        (InfrastructureKind.IPV4, "8.8.8.8"),
        (InfrastructureKind.IPV4, "192.168.12.4"),
        (InfrastructureKind.IPV4, "127.0.0.1"),
    }


@pytest.mark.unit
def test_ipv4_invalid_octet_and_version_quad_rejected() -> None:
    # 999 is out of range; a 5-part version string is not a 4-octet IP.
    assert _find_ips("ver 1.2.3.4.5 build 999.1.1.1") == set()


@pytest.mark.unit
def test_ipv6_extracted_and_compressed_dedup() -> None:
    # Expanded and compressed forms of the same global address collapse to one.
    found = _find_ips("hit 2606:4700:4700:0000:0000:0000:0000:1111 == 2606:4700:4700::1111")
    assert found == {(InfrastructureKind.IPV6, "2606:4700:4700::1111")}


@pytest.mark.unit
def test_ipv6_keeps_loopback_drops_unspecified_rejects_macish() -> None:
    # ::1 loopback kept (non-global but real); :: unspecified dropped; a MAC-style
    # token and a one-colon time are not valid IPv6 and never become candidates.
    assert _find_ips("loop ::1 un :: mac 00:11:22:33:44:55 time 12:34") == {
        (InfrastructureKind.IPV6, "::1")
    }


@pytest.mark.unit
def test_malformed_url_does_not_crash() -> None:
    # urlsplit() raises ValueError on an unbalanced-bracket URL; _extract must skip
    # it, not propagate (one bad URL in a message once killed a whole backfill).
    found = _extract("see http://[abc broken and real badplace.io here")
    assert (InfrastructureKind.DOMAIN, "badplace.io") in found


@pytest.mark.unit
def test_bare_domain_psl_validated() -> None:
    found = _find_bare_domains("mirror on evil-shop.su today")
    assert found == {(InfrastructureKind.DOMAIN, "evil-shop.su")}


@pytest.mark.unit
def test_bare_domain_rejects_non_tld_tokens() -> None:
    # report.pdf / node.js have no real TLD; tldextract returns an empty suffix.
    assert _find_bare_domains("open report.pdf with node.js runtime") == set()


@pytest.mark.unit
def test_bare_domain_skips_email_and_onion() -> None:
    # Email domain (owned by the email rule) and onion (owned by the onion pass).
    text = "contact user@evil.su via " + "a" * 56 + ".onion"
    assert _find_bare_domains(text) == set()


@pytest.mark.unit
def test_extract_unions_domains_and_ips() -> None:
    found = _extract("shop badplace.io at 185.220.101.5")
    assert (InfrastructureKind.DOMAIN, "badplace.io") in found
    assert (InfrastructureKind.IPV4, "185.220.101.5") in found


@pytest.mark.unit
async def test_ip_artifacts_persisted_with_open_kind(storage: BaseRepository) -> None:
    written = await UrlExtractor().process(_ctx("c2 1.1.1.1 and ::"), storage)
    assert written == 1  # one global IPv4; :: is unspecified (non-global), dropped
    again = await storage.put_infrastructure_artifact(
        kind="ipv4",
        value="203.0.113.7",
        first_seen_at_ingest=_NOW,
        last_seen_at_ingest=_NOW,
    )
    assert again.kind == "ipv4"


def test_url_artifact_emitted_with_domain_host() -> None:
    got = _extract("join https://t.me/joinChat/AbC123?x=1#frag now")
    # full URL kept (path case preserved, fragment dropped) AND the bare host
    assert (InfrastructureKind.URL, "https://t.me/joinChat/AbC123?x=1") in got
    assert (InfrastructureKind.DOMAIN, "t.me") in got


def test_url_artifact_emitted_for_ip_host() -> None:
    got = _extract("panel at http://185.220.101.5:8080/login")
    assert (InfrastructureKind.URL, "http://185.220.101.5:8080/login") in got
    assert (InfrastructureKind.IPV4, "185.220.101.5") in got


def test_url_artifact_skipped_for_garbage_host() -> None:
    # bogus TLD -> not a domain, not an IP -> no URL artifact
    got = _extract("see http://notarealtld.zzzzz/x")
    assert not any(k == InfrastructureKind.URL for k, _ in got)
