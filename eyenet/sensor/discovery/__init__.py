# SPDX-License-Identifier: AGPL-3.0-or-later
"""Discovery extractors — the side-effecting sensor seam (API_PLAN §4.12, M9.E1-E2).

Distinct from the stylometric primitives (`eyenet/sensor/primitives/`), which are
pure ``compute(corpus, bodies) -> Observation`` functions. A *discovery extractor*
runs per message with full collector/group/actor context (:class:`MessageContext`)
and **writes storage directly** — InfrastructureArtifact rows (E1 `url_extraction`)
or GroupCandidateMention rows (E2 `channel_reference_extraction`) — so it cannot
fit the pure-function primitive contract.

The live dispatcher (envelope → resolved :class:`MessageContext` → run the
registry) is the ``DiscoverySensor`` service that lands with E2, where channel
extraction forces the id-resolution path. E1's extractor is unit-tested directly
against a constructed context.
"""

from __future__ import annotations

from ._base import DiscoveryExtractor, MessageContext
from .channel_reference_extraction import ChannelReferenceExtractor
from .url_extraction import UrlExtractor

# The extractor registry the DiscoverySensor (E2) iterates per raw message.
DISCOVERY_EXTRACTORS: tuple[DiscoveryExtractor, ...] = (
    UrlExtractor(),
    ChannelReferenceExtractor(),
)

__all__ = [
    "DISCOVERY_EXTRACTORS",
    "ChannelReferenceExtractor",
    "DiscoveryExtractor",
    "MessageContext",
    "UrlExtractor",
]
