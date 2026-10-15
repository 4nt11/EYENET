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

from typing import TYPE_CHECKING

from ._base import DiscoveryExtractor, MessageContext
from .channel_reference_extraction import ChannelReferenceExtractor
from .indicator_extraction import IndicatorExtractor
from .url_extraction import UrlExtractor

if TYPE_CHECKING:
    from eyenet.bus.publisher import BusEnvelopePublisher


def build_discovery_extractors(
    publisher: BusEnvelopePublisher | None = None,
) -> tuple[DiscoveryExtractor, ...]:
    """The extractor registry the DiscoverySensor iterates per raw message.

    ``publisher`` is threaded to the artifact-creating extractors so a new artifact
    emits ``entity.artifact.changed`` for live search reindexing; omit it (the
    module default) for the publisher-less registry used by direct-call tests.
    """
    return (
        UrlExtractor(publisher),
        ChannelReferenceExtractor(),
        IndicatorExtractor(publisher),
    )


# Publisher-less default registry (direct-call tests + membership checks).
DISCOVERY_EXTRACTORS: tuple[DiscoveryExtractor, ...] = build_discovery_extractors()

__all__ = [
    "DISCOVERY_EXTRACTORS",
    "ChannelReferenceExtractor",
    "DiscoveryExtractor",
    "IndicatorExtractor",
    "MessageContext",
    "UrlExtractor",
    "build_discovery_extractors",
]
