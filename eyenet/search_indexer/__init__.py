# SPDX-License-Identifier: AGPL-3.0-or-later
"""Global-search indexing (GLOBAL_SEARCH.md).

- ``backfill.backfill_search`` — the one-shot corpus bootstrap (``eyenet
  search-backfill``), read-only over the source tables.
- ``service.SearchIndexerService`` — the live, event-driven indexer: subscribes
  to ``entity.>`` (change-gated actor/group/case events), ``raw.message.>``,
  ``attribution.persona.updated`` and the classify events, and reindexes the one
  entity named in each.
- ``events.publish_entity_changed`` — the emit helper write paths call.
- ``haystack`` — the shared per-entity payload builders (backfill + service).

Submodules are imported directly (no eager re-export) so importing ``events`` on
the collector hot path does not pull in the backfill/service machinery.
"""
