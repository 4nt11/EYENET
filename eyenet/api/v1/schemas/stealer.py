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


# v1.3.3 per-victim artifact drawer surface.
# One row per (archive_sha256, victim_folder) backs the card + drawer.


class StealerArtifactCard(ApiSchema):
    """Compact card row for the left-panel artifact list."""

    archive_sha256: str
    victim_folder: str
    country: str
    traffic_affid: str
    build_version: str
    creds_count: int
    cookies_count: int
    wallet_vaults_count: int
    has_corporate_marker: bool
    has_wallet: bool
    has_crypter_banner: bool


class StealerArtifactsResponse(ApiSchema):
    """List payload for the artifacts left panel."""

    initialized: bool = True
    items: list[StealerArtifactCard]
    page_meta: StealerAuditPageMeta


class StealerArtifactStatTiles(ApiSchema):
    """Stat tiles row at the top of the drawer header."""

    credentials: int
    domain_hits: int  # monitored-domain match count; 0 until monitored_domains ships
    cookies: int
    country: str
    related: int  # other artifacts sharing a key join field; 0 until implemented
    # v1.3.6 parse coverage. file_audit_per_victim.parsed_files / total_files
    # expressed as a %; absolute counts help the operator judge sample size
    # ("48% parsed" of 2 files is noisier than 48% of 200).
    coverage_pct: float = 0.0
    coverage_total: int = 0
    coverage_parsed: int = 0


class StealerTechnique(ApiSchema):
    """One MITRE ATT&CK technique badge for the Overview tab."""

    technique_id: str  # e.g. 'T1555.003'
    name: str
    tactic: str
    tactic_id: str
    url: str
    fired_from_rules: list[str]  # which rule_ids triggered this technique


class StealerFamilyCount(ApiSchema):
    """Per-family victim count, keyed by verdict slug. The empty slug is
    the no-verdict bucket."""

    slug: str
    count: int


class StealerFamilyCountsResponse(ApiSchema):
    initialized: bool = True
    items: list[StealerFamilyCount]


class StealerFamilyOverrideIn(ApiSchema):
    slug: str
    reason: str | None = None


class StealerFamilyOverrideOut(ApiSchema):
    archive_sha256: str
    victim_folder: str
    slug: str
    reason: str | None = None
    author_user_id: str
    created_at: str
    updated_at: str


class StealerFamilyRunnerUp(ApiSchema):
    slug: str
    confidence: float


class StealerFamilyVerdict(ApiSchema):
    """Per-victim stealer-family verdict rendered in the drawer header.

    ``slug`` is the empty string when no verdict row exists yet (classifier
    has not run or the scorer did not clear any family's confidence
    floor). ``runners_up`` is the next few ranked slugs regardless of
    floor so the evidence popover shows the scorer's state of mind even
    on a no-verdict. See
    ``development/STEALER_FAMILY_CLASSIFIER_DESIGN.md``.
    """

    slug: str
    confidence: float
    evidence: list[str]
    runners_up: list[StealerFamilyRunnerUp]


class StealerArtifactDetail(ApiSchema):
    """Drawer detail: header + stat tiles + full profile fields.

    MITRE ATT&CK techniques are resolved server-side via a join between
    the artifact's fired rule_ids and the mitre_catalog.yaml file, so
    the FE gets ready-to-render technique rows.
    """

    archive_sha256: str
    victim_folder: str
    source: str
    # identity
    country: str
    egress_ip: str
    user_name: str
    computer_name: str
    os_version: str
    # attribution
    traffic_affid: str
    build_version: str
    payload_md5: str
    work_dir: str
    # counts (Overview tab + stat tiles)
    stat_tiles: StealerArtifactStatTiles
    creds_count: int
    cookies_count: int
    autofills_count: int
    history_count: int
    downloads_count: int
    processes_count: int
    software_count: int
    discord_tokens_count: int
    steam_tokens_count: int
    google_refresh_count: int
    localstorage_jwt_count: int
    wallet_vaults_count: int
    # presence flags
    has_corporate_marker: bool
    has_webmail_leak: bool
    has_wallet: bool
    has_crypter_banner: bool
    # highlights
    webmail_identity: str
    first_corporate_marker: str
    first_wallet_family: str
    # ATT&CK techniques derived from fired rules
    techniques: list[StealerTechnique]
    # Per-victim stealer-family verdict. slug == "" means no confident
    # verdict yet; runners_up is populated even on no-verdict so the
    # evidence popover shows the scorer's ranking.
    suspected_family: StealerFamilyVerdict


class StealerArtifactFileRow(ApiSchema):
    """One file row in the Files tab tree."""

    rel_path: str
    filename: str
    size_bytes: int
    heuristic_kind: str
    extractor_touched: bool
    rows_emitted: int
    sample_head: str
    file_sha256: str


class StealerArtifactFilesResponse(ApiSchema):
    initialized: bool = True
    archive_sha256: str
    victim_folder: str
    items: list[StealerArtifactFileRow]


class StealerArtifactRecordRow(ApiSchema):
    """One extracted-record row (Credentials / System / Audit / etc tabs)."""

    rule_id: str
    family: str
    file_path: str
    fields: dict[str, str]


class StealerArtifactRecordsResponse(ApiSchema):
    initialized: bool = True
    archive_sha256: str
    victim_folder: str
    items: list[StealerArtifactRecordRow]
    page_meta: StealerAuditPageMeta


class StealerArtifactDomainRow(ApiSchema):
    """One domain-hit row for the drawer's EXTRACTED INDICATORS section."""

    domain: str
    source_kind: (
        str  # cookie | credential | history_visit | download | localstorage | email_webmail
    )
    count: int


class StealerArtifactDomainsResponse(ApiSchema):
    initialized: bool = True
    archive_sha256: str
    victim_folder: str
    items: list[StealerArtifactDomainRow]


# v1.3.6 parse-failures workbench. Grouped by shape fingerprint computed
# in SQL from file_audit.sample_head; a "shape" row is the aggregate card
# that drives the workbench table, and samples are the raw file-level
# rows behind it, surfaced on expand or on the "Draft rule from file"
# action.
class StealerFailureShape(ApiSchema):
    shape_sig: str  # character-class signature key
    shape_preview: str  # same signature, trimmed for UI header
    count: int  # how many files fell into this shape bucket
    victims: int  # distinct (archive_sha256, victim_folder) pairs
    archives: int  # distinct archives
    sample: str  # one representative sample_head from the bucket
    sample_archive_sha256: str
    sample_victim_folder: str
    sample_file_path: str
    heuristic_kind: str
    filenames: list[str]  # top N distinct filenames seen in the bucket


class StealerFailuresResponse(ApiSchema):
    initialized: bool = True
    items: list[StealerFailureShape]
    page_meta: StealerAuditPageMeta


class StealerFailureSampleRow(ApiSchema):
    archive_sha256: str
    victim_folder: str
    file_path: str
    filename: str
    size_bytes: int
    sample_head: str
    heuristic_kind: str


class StealerFailureSamplesResponse(ApiSchema):
    shape_sig: str
    items: list[StealerFailureSampleRow]


class StealerFailuresStats(ApiSchema):
    """Corpus-wide tiles for the parse-failures workbench header.

    coverage_pct = parsed_files / total_files * 100 across the whole corpus
    (not filtered by the row-level workbench filters). fail_files is the
    total count of files behind the shape buckets ( extractor matched a
    path_glob but 0 records came out). crash_files is the count of files
    where gotractor itself panicked: a hard error distinct from the
    softer "rule matched, 0 records" case.
    """

    initialized: bool = True
    total_files: int = 0
    parsed_files: int = 0
    coverage_pct: float = 0.0
    fail_files: int = 0
    shape_buckets: int = 0
    crash_files: int = 0


__all__ = [
    "StealerArtifactCard",
    "StealerArtifactDetail",
    "StealerArtifactDomainRow",
    "StealerArtifactDomainsResponse",
    "StealerArtifactFileRow",
    "StealerArtifactFilesResponse",
    "StealerArtifactRecordRow",
    "StealerArtifactRecordsResponse",
    "StealerArtifactStatTiles",
    "StealerArtifactsResponse",
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
    "StealerFailureSampleRow",
    "StealerFailureSamplesResponse",
    "StealerFailureShape",
    "StealerFailuresResponse",
    "StealerFailuresStats",
    "StealerFamilyCount",
    "StealerFamilyCountsResponse",
    "StealerFamilyOverrideIn",
    "StealerFamilyOverrideOut",
    "StealerFamilyRunnerUp",
    "StealerFamilyVerdict",
    "StealerSearchResponse",
    "StealerStatsResponse",
    "StealerTechnique",
]
