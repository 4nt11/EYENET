# SPDX-License-Identifier: AGPL-3.0-or-later
"""Global-search indexing (GLOBAL_SEARCH.md).

Phase 1 ships the ONE-SHOT BACKFILL (`backfill.py`) that populates
``search_document`` from the existing corpus — the operator-run bootstrap that
makes ``GET /v1/search`` return results. It is read-only over the source tables
and writes only ``search_document`` via the bulk upsert, so it is safe to run
against the live operating DB.

The live, event-driven ``SearchIndexer`` service (subscribing to ``raw.message.>``
et al.) and the new actor/group/case domain events are the remaining Phase 1
freshness layer — deferred to land with live-NATS validation, since they touch
the ingest/producer paths. Until then, re-run the backfill to refresh the index.
"""

from eyenet.search_indexer.backfill import backfill_search

__all__ = ["backfill_search"]
