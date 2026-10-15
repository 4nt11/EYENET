# SPDX-License-Identifier: AGPL-3.0-or-later
"""`url_extraction` discovery extractor (API_PLAN §4.12, M9.E1).

Pulls network artifacts out of message text, normalizes them, and upserts
InfrastructureArtifact rows: domains (from URLs and bare, PSL-validated), onion
hosts, and IPv4/IPv6 literals. ``put_infrastructure_artifact`` runs §2.25 Path-A
bridge resolution inline, so a host that matches an existing SourceDomain is
recorded RESOLVED and one that doesn't stays UNRESOLVED — both in the same call.

Domains and IPs are CODED, not ruleset (a simple regex can't tell a real domain
from ``report.pdf`` or an IP from a version string): domains go through
tldextract (Public Suffix List) so only a token with a real TLD is kept; IPs go
through a regex candidate pass then :mod:`ipaddress` validation, which also
separates ``ipv4`` from ``ipv6`` and lets us drop non-global addresses. The
extractor name stays ``url_extraction`` (stable cursor identity) though it now
covers more than URLs.

Normalization collapses unicode ↔ punycode duplicates: ``münchen.de`` and
``xn--mnchen-3ya.de`` reduce to one ``value`` (hence one ``value_hash``, hence
one artifact). Onion hosts bypass IDNA (they're already base32 ASCII) and are
classified ``ONION`` rather than ``DOMAIN``. IPv6 is stored compressed+lowercase
(``2001:db8::1``) so textual variants dedup to one artifact.
"""

from __future__ import annotations

import ipaddress
import re
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

import tldextract

from eyenet.contracts.enums import InfrastructureKind
from eyenet.search_indexer.events import publish_entity_changed
from eyenet.telemetry.logging import get_logger
from eyenet.util.domain import normalize_host

from ._base import DiscoveryExtractor

if TYPE_CHECKING:
    from eyenet.bus.publisher import BusEnvelopePublisher
    from eyenet.storage.repository import BaseRepository

    from ._base import MessageContext

_log = get_logger()

# Scheme-qualified URLs. Stop at whitespace and common trailing delimiters so a
# URL inside prose / brackets / quotes doesn't swallow the punctuation.
_URL_RE = re.compile(r"https?://[^\s<>\"'\)\]\}]+", re.IGNORECASE)
# Standalone onion addresses (v2 = 16 base32 chars, v3 = 56), not requiring a
# scheme — threat-actor text drops these bare constantly.
_ONION_RE = re.compile(r"\b[a-z2-7]{16}\.onion\b|\b[a-z2-7]{56}\.onion\b", re.IGNORECASE)

# Bare dotted-label domain candidate. Lookbehind skips an ``@`` (that domain is
# an email local-part's domain — the email rule owns it) and mid-label starts;
# lookahead skips ``domain@...`` and partial tails. tldextract does the real
# accept/reject against the PSL — this only finds plausible tokens cheaply.
_DOMAIN_CAND = re.compile(
    r"(?<![@\w.-])((?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9][a-z0-9-]{0,61}[a-z0-9])(?![@\w])",
    re.IGNORECASE,
)
# IPv4 candidate: four dotted octets, bounded so a 5+ part version string
# (1.2.3.4.5) does NOT yield a spurious IP. ipaddress validates the ranges.
_IPV4_CAND = re.compile(r"(?<![\w.])\d{1,3}(?:\.\d{1,3}){3}(?![\w.])")
# IPv6 candidate: >=2 colon-separated hex groups (so a time/MAC with one colon is
# not a candidate), optional embedded v4 tail. Broad on purpose — ipaddress is
# the real gate; over-matched junk fails parsing and is dropped.
_IPV6_CAND = re.compile(r"(?<![\w:.])(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f.]{0,15}(?![\w:])")

_ONION_SUFFIX = ".onion"

# Offline PSL: the bundled snapshot only, never a network fetch (honors the
# curl/wget block; deterministic in the collector env) and no disk cache writes
# (cache_dir=None — safe in a locked-down container fs). One instance, module-wide.
_tld = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)


def _classify_and_normalize(host: str) -> tuple[InfrastructureKind, str] | None:
    """Return ``(kind, normalized_value)`` for a host, or None if unusable."""
    host = host.strip().rstrip(".").lower()
    if not host:
        return None
    if host.endswith(_ONION_SUFFIX):
        # Onion addresses are already ASCII base32; IDNA would only reject them.
        return (InfrastructureKind.ONION, host)
    try:
        return (InfrastructureKind.DOMAIN, normalize_host(host))
    except ValueError:
        # Malformed / non-IDNA host (e.g. an IP literal, confusable mixed
        # script). Skip it — a bad host is not an extractable artifact.
        _log.debug("url_extraction.skip_invalid_host", host=host)
        return None


def _find_bare_domains(text: str) -> set[tuple[InfrastructureKind, str]]:
    """Bare domains in free text, PSL-validated. Onion tokens are left to the
    onion pass; a candidate with no real TLD (``report.pdf``, ``node.js``) is
    dropped because tldextract returns an empty suffix for it."""
    found: set[tuple[InfrastructureKind, str]] = set()
    for m in _DOMAIN_CAND.finditer(text):
        cand = m.group(1)
        if cand.lower().endswith(_ONION_SUFFIX):
            continue
        ext = _tld(cand)
        if not (ext.suffix and ext.domain):
            continue  # suffix not in the Public Suffix List -> not a domain
        try:
            found.add((InfrastructureKind.DOMAIN, normalize_host(cand)))
        except ValueError:
            continue
    return found


def _find_ips(text: str) -> set[tuple[InfrastructureKind, str]]:
    """IPv4/IPv6 literals, ipaddress-validated. Non-global addresses (private,
    loopback, reserved, link-local) are dropped — they are config/example noise,
    not operator infrastructure. ponytail: a global quad like ``1.2.3.4`` that is
    really a version string is an accepted false positive; context-gating is a
    later add if it proves noisy."""
    found: set[tuple[InfrastructureKind, str]] = set()
    for m in _IPV4_CAND.finditer(text):
        try:
            ip4 = ipaddress.IPv4Address(m.group(0))
        except ValueError:
            continue
        if ip4.is_global:
            found.add((InfrastructureKind.IPV4, str(ip4)))
    for m in _IPV6_CAND.finditer(text):
        try:
            ip6 = ipaddress.IPv6Address(m.group(0))
        except ValueError:
            continue
        if ip6.is_global:
            found.add((InfrastructureKind.IPV6, ip6.compressed))
    return found


def _extract(text: str) -> set[tuple[InfrastructureKind, str]]:
    """Return the distinct ``(kind, normalized_value)`` artifacts in ``text``."""
    found: set[tuple[InfrastructureKind, str]] = set()
    for match in _URL_RE.finditer(text):
        host = urlsplit(match.group(0)).hostname
        if host:
            classified = _classify_and_normalize(host)
            if classified is not None:
                found.add(classified)
    for match in _ONION_RE.finditer(text):
        classified = _classify_and_normalize(match.group(0))
        if classified is not None:
            found.add(classified)
    found |= _find_bare_domains(text)
    found |= _find_ips(text)
    return found


class UrlExtractor(DiscoveryExtractor):
    """Extract network artifacts (domains, onions, IPv4/IPv6) from message text."""

    name = "url_extraction"

    def __init__(self, publisher: BusEnvelopePublisher | None = None) -> None:
        # When set, publish entity.artifact.changed for live SearchIndexer reindex.
        self._publisher = publisher

    async def process(self, ctx: MessageContext, storage: BaseRepository) -> int:
        artifacts = _extract(ctx.text)
        if not artifacts:
            return 0
        # Provenance edge back to the message (best-effort: the message is
        # normally persisted before discovery runs, but older direct-call sites
        # pass a context whose message is not stored).
        message_id = await storage.get_message_id_by_evidence_ref(ctx.evidence_ref)
        for kind, value in artifacts:
            artifact = await storage.put_infrastructure_artifact(
                kind=kind,
                value=value,
                first_seen_at_ingest=ctx.collected_at,
                last_seen_at_ingest=ctx.collected_at,
            )
            if message_id is not None:
                inserted = await storage.record_artifact_mention(
                    artifact_id=artifact.id,
                    message_id=message_id,
                    char_offset=None,
                    ts=ctx.sent_at_source,
                )
                if inserted and self._publisher is not None:
                    await publish_entity_changed(
                        self._publisher,
                        entity_type="artifact",
                        entity_id=artifact.id,
                        source_id=artifact.resolved_to_source_id,
                    )
        return len(artifacts)


__all__ = ["UrlExtractor"]
