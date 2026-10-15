# SPDX-License-Identifier: AGPL-3.0-or-later
"""`url_extraction` discovery extractor (API_PLAN §4.12, M9.E1).

Pulls hosts out of message text, normalizes them, and upserts
InfrastructureArtifact rows. ``put_infrastructure_artifact`` runs §2.25 Path-A
bridge resolution inline, so a host that matches an existing SourceDomain is
recorded RESOLVED and one that doesn't stays UNRESOLVED — both in the same call.

Normalization collapses unicode ↔ punycode duplicates: ``münchen.de`` and
``xn--mnchen-3ya.de`` reduce to one ``value`` (hence one ``value_hash``, hence
one artifact). Onion hosts bypass IDNA (they're already base32 ASCII) and are
classified ``ONION`` rather than ``DOMAIN``.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

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

_ONION_SUFFIX = ".onion"


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
    return found


class UrlExtractor(DiscoveryExtractor):
    """Extract host artifacts (domains + onions) from message text (M9.E1)."""

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
