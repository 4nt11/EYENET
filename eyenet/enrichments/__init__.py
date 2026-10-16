# SPDX-License-Identifier: AGPL-3.0-or-later
"""Enrichment plugins for the graph exploration canvas.

Add an enrichment by dropping a concrete :class:`Enrichment` subclass into
``eyenet/enrichments/builtins/`` (DB-backed) or ``eyenet/enrichments/remote/``
(external service). It is autodiscovered and registered by ``(src_type, name)``;
nothing central needs editing.
"""

from __future__ import annotations

from eyenet.enrichments.base import (
    Enrichment,
    ExpandContext,
    ExpandNode,
    ExpandResult,
    LocalSQLEnrichment,
    RemoteEnrichment,
)
from eyenet.enrichments.registry import (
    discover,
    enrichments_for_src_type,
    get_enrichment,
)

__all__ = [
    "Enrichment",
    "ExpandContext",
    "ExpandNode",
    "ExpandResult",
    "LocalSQLEnrichment",
    "RemoteEnrichment",
    "discover",
    "enrichments_for_src_type",
    "get_enrichment",
]
