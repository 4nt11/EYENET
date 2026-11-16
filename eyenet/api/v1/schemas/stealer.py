# SPDX-License-Identifier: AGPL-3.0-or-later
"""Read schemas for the ULP corpus surface (stealer stats + credential search)."""

from __future__ import annotations

from ._base import ApiSchema


class StealerBucket(ApiSchema):
    """One (key, count) bar for a distribution chart."""

    key: str
    count: int


class StealerStatsResponse(ApiSchema):
    """Overview of the stealer-creds corpus for the dashboard charts + tiles.

    ``initialized`` is False when the ClickHouse `stealer.creds` table has not
    been created yet (no stealer channel has ever been ingested). In that case
    all counters are zero and the lists are empty; the dashboard should render
    a "connect a stealer channel" hint instead of empty charts.
    """

    initialized: bool = True
    total_creds: int
    unique_creds: int
    distinct_hosts: int
    by_scheme: list[StealerBucket]
    by_tld: list[StealerBucket]  # ccTLD of the service host (country-ish signal)
    top_hosts: list[StealerBucket]


class StealerCred(ApiSchema):
    """One credential row from a host search (read:stealer — full content)."""

    host: str
    url: str
    login: str
    password: str
    scheme: str
    tld: str


class StealerSearchResponse(ApiSchema):
    """A page of credential hits for a host search.

    ``initialized`` is False when the ClickHouse `stealer.creds` table has not
    been created yet; `items` is empty in that case. See `StealerStatsResponse`.
    """

    initialized: bool = True
    items: list[StealerCred]


class StealerAuditCoverageRow(ApiSchema):
    """Per-archive parse coverage, for the Corpus Health scorecard."""

    archive_sha256: str
    total_files: int
    parsed_files: int
    unknown_files: int
    pct_parsed: float
    first_seen_at: str


class StealerAuditUnknownRow(ApiSchema):
    """Filename + heuristic + representative sample for files we see but do
    not parse. Each row is one next-rule-to-write candidate."""

    filename: str
    heuristic_kind: str
    occurrences: int
    archive_count: int
    sample_head: str


class StealerAuditSampleRow(ApiSchema):
    """One sample_head snippet for a specific filename, for rule-authoring."""

    archive_sha256: str
    rel_path: str
    size_bytes: int
    sample_head: str


class StealerAuditSearchRow(ApiSchema):
    """One corpus-search hit. ``match_context`` is roughly 200 chars centered
    on the first substring hit inside sample_head."""

    archive_sha256: str
    rel_path: str
    filename: str
    heuristic_kind: str
    size_bytes: int
    match_context: str


class StealerAuditPageMeta(ApiSchema):
    """Pagination envelope shared across every audit list endpoint.

    ``total`` and ``page_count`` are always populated. For /coverage and
    /unknown they come from a cheap ``uniqExact`` against a pre-aggregated
    materialized view; for /samples and /search they come from a ``count()``
    with WHERE against the ngram-indexed file_audit table (prunes granules
    by bloom-filter presence). ``has_more`` is ``page < page_count`` and is
    returned for FE convenience so a "Next" button doesn't need to compute
    it client-side."""

    page: int
    limit: int
    total: int
    page_count: int
    has_more: bool


class StealerAuditCoverageResponse(ApiSchema):
    initialized: bool = True
    items: list[StealerAuditCoverageRow]
    page_meta: StealerAuditPageMeta


class StealerAuditUnknownResponse(ApiSchema):
    initialized: bool = True
    items: list[StealerAuditUnknownRow]
    page_meta: StealerAuditPageMeta


class StealerAuditSamplesResponse(ApiSchema):
    initialized: bool = True
    items: list[StealerAuditSampleRow]
    page_meta: StealerAuditPageMeta


class StealerAuditSearchResponse(ApiSchema):
    initialized: bool = True
    items: list[StealerAuditSearchRow]
    page_meta: StealerAuditPageMeta


__all__ = [
    "StealerAuditCoverageResponse",
    "StealerAuditCoverageRow",
    "StealerAuditPageMeta",
    "StealerAuditSampleRow",
    "StealerAuditSamplesResponse",
    "StealerAuditSearchResponse",
    "StealerAuditSearchRow",
    "StealerAuditUnknownResponse",
    "StealerAuditUnknownRow",
    "StealerBucket",
    "StealerCred",
    "StealerSearchResponse",
    "StealerStatsResponse",
]
