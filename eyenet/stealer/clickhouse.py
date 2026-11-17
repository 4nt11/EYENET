# SPDX-License-Identifier: AGPL-3.0-or-later
"""ClickHouse sink for extracted ULP credentials.

Thin wrapper over clickhouse-connect (HTTP). Owns the ``stealer.creds``
ReplacingMergeTree schema (dedup key == ``(host, login, password)``) and a batched
insert from ulpextract's TSV columns. clickhouse-connect is an OPTIONAL dep shipped
in the stealer profile image, so it's imported lazily — the core stack never needs it.

Config via env: ``EYENET_CLICKHOUSE_HOST`` (default "clickhouse"), ``_PORT`` (8123),
``_USER`` (default "default"), ``_PASSWORD`` (default ""), ``_DB`` (default "stealer").
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

    from clickhouse_connect.driver.client import Client

# ulpextract emits these columns, tab-separated, in this order.
_COLUMNS = [
    "host", "url", "login", "password", "scheme", "tld", "source", "ip_class", "source_file"
]

_CREATE_DB = "CREATE DATABASE IF NOT EXISTS {db}"
# ReplacingMergeTree collapses rows with identical (host, login, password) on merge,
# keeping max(ingested). url/scheme/tld/source/ip_class are payload, not identity.
#
# `storage_policy` is injected by _storage_policy_clause() from the
# EYENET_CLICKHOUSE_STORAGE_POLICY env var: on prod lite this is
# 'wasabi_primary' (see clickhouse/config.d/wasabi-storage.xml) so the corpus
# lives on Wasabi with a local SSD cache; on dev the var is unset and CH
# uses the implicit `default` local policy. Changing the policy of an
# existing table is a separate `ALTER TABLE creds MODIFY SETTING
# storage_policy=...` + data move, not a redeploy.
_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS {db}.creds
(
    host        String,
    url         String,
    login       String,
    password    String,
    scheme      LowCardinality(String) DEFAULT '',
    tld         LowCardinality(String) DEFAULT '',
    source      LowCardinality(String) DEFAULT '',
    ip_class    LowCardinality(String) DEFAULT '',
    source_file String                 DEFAULT '',
    ingested    DateTime               DEFAULT now()
)
ENGINE = ReplacingMergeTree(ingested)
ORDER BY (host, login, password)
{storage_policy_clause}
"""

# Schema-upgrade DDL idempotently applied after _CREATE_TABLE on every
# ``ensure_schema`` call. Each statement must be an ``ALTER TABLE ... IF
# NOT EXISTS`` (or MODIFY-COLUMN-safe equivalent) so re-running against an
# already-upgraded table is a no-op. CH 24.x supports IF NOT EXISTS on
# ADD COLUMN. Keep oldest-first; never remove a line, even after it has
# been in every running cluster for a release, so a long-skipped operator
# upgrading across multiple versions still catches it.
_ALTER_TABLE = (
    # v1.2.5 - per-record source file (the ulpextract inner path). Earlier
    # releases dropped this on the floor via fields[6] overwrite; now kept
    # as its own column so a bad row traces back to the file that produced
    # it, and the v1.3.0 infections join has a key to attach on.
    "ALTER TABLE {db}.creds ADD COLUMN IF NOT EXISTS source_file String DEFAULT ''",
)


def _storage_policy_clause() -> str:
    """`SETTINGS storage_policy='<name>'` when EYENET_CLICKHOUSE_STORAGE_POLICY
    is set, empty string otherwise. Kept dumb on purpose: CH itself validates
    the name at CREATE TABLE and fails loud if the policy does not exist."""
    policy = os.environ.get("EYENET_CLICKHOUSE_STORAGE_POLICY", "").strip()
    if not policy:
        return ""
    # CH policy names are identifiers (letters/digits/underscore); reject
    # anything else so an operator typo can never land as SQL.
    if not all(c.isalnum() or c == "_" for c in policy):
        raise ValueError(
            f"EYENET_CLICKHOUSE_STORAGE_POLICY={policy!r} is not a valid policy name "
            "(alphanumeric + underscore only)"
        )
    return f"SETTINGS storage_policy = '{policy}'"


def clickhouse_db() -> str:
    return os.environ.get("EYENET_CLICKHOUSE_DB", "stealer")


def get_clickhouse_client() -> Client:
    """A clickhouse-connect client from EYENET_CLICKHOUSE_* env. Shared by the creds
    sink (processor) and the read API (search/stats)."""
    import clickhouse_connect  # noqa: PLC0415 — dep present in core + stealer images

    return clickhouse_connect.get_client(
        host=os.environ.get("EYENET_CLICKHOUSE_HOST", "clickhouse"),
        port=int(os.environ.get("EYENET_CLICKHOUSE_PORT", "8123")),
        username=os.environ.get("EYENET_CLICKHOUSE_USER", "default"),
        password=os.environ.get("EYENET_CLICKHOUSE_PASSWORD", ""),
    )


class ClickHouseCredsSink:
    """Connection + schema + batched credential insert for ``<db>.creds``."""

    def __init__(self) -> None:
        self._db = clickhouse_db()
        self._client: Client | None = None

    def _connect(self) -> Client:
        if self._client is None:
            self._client = get_clickhouse_client()
        return self._client

    def ensure_schema(self) -> None:
        """Create the database + creds table if absent AND apply the idempotent
        ALTER chain (``_ALTER_TABLE``) so an older cluster upgrades in place
        without an operator action."""
        client = self._connect()
        client.command(_CREATE_DB.format(db=self._db))
        client.command(
            _CREATE_TABLE.format(
                db=self._db,
                storage_policy_clause=_storage_policy_clause(),
            )
        )
        for alter in _ALTER_TABLE:
            client.command(alter.format(db=self._db))

    def insert_rows(self, rows: Iterable[list[str]]) -> int:
        """Insert cred rows (each a value list matching ``_COLUMNS``). Returns
        the number inserted. Caller batches; this is one INSERT per call."""
        batch: list[list[Any]] = list(rows)
        if not batch:
            return 0
        self._connect().insert(f"{self._db}.creds", batch, column_names=_COLUMNS)
        return len(batch)

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None


# v1.3.1 gotractor landing table. One row per EXTRACTED RECORD from the
# new Go DSL engine (replaces ulpextract's fixed 8-col TSV with a
# rule-driven schema). Key invariants:
#
#   - `fields` is a Map(String, String) so any rule's extract map lands
#     here without a migration per field (if a column ends up load-
#     bearing enough to warrant promotion, we materialize it with a
#     dedicated column later; MergeTree supports ADD COLUMN cheaply).
#   - The dedup key is (archive_sha256, rule_id, file_path, hash of
#     fields) via a MATERIALIZED version column, so re-running the
#     pipeline on the same archive collapses duplicates on merge
#     instead of leaving them in the table.
#   - LowCardinality on family + rule_id because both are enum-shaped
#     (dozens of distinct values, millions of rows).
_RECORDS_CREATE = """
CREATE TABLE IF NOT EXISTS {db}.extracted_records
(
    archive_sha256  FixedString(64),
    source          LowCardinality(String),
    victim_folder   String,
    file_path       String,
    rule_id         LowCardinality(String),
    family          LowCardinality(String),
    fields          Map(String, String),
    ingested_at     DateTime DEFAULT now(),
    INDEX idx_family family TYPE set(0) GRANULARITY 1,
    INDEX idx_rule_id rule_id TYPE set(0) GRANULARITY 1
)
ENGINE = ReplacingMergeTree(ingested_at)
ORDER BY (archive_sha256, rule_id, file_path, cityHash64(toString(fields)))
{storage_policy_clause}
"""


_RECORDS_COLUMNS = [
    "archive_sha256", "source", "victim_folder", "file_path",
    "rule_id", "family", "fields",
]


# v1.3.3 per-victim profile roll-up. ONE row per (archive_sha256, victim_folder)
# that the FE lists + filters + opens in a detail drawer. Cheap enough to
# query without FINAL because archive_sha256 is the sort-key prefix.
#
# Why AggregatingMergeTree + SimpleAggregateFunction:
#   - The pipeline inserts into extracted_records in batches of ~1000 rows.
#     For a Khazan archive (~200k records across ~450 victims) that is many
#     MV firings per archive. Each MV firing produces one row per
#     (archive, victim) touched in the batch.
#   - SAF(sum, UInt32) on counts: batches add together on background merge.
#   - SAF(max, String) on identity fields: lexicographic max selects a
#     non-empty value over an empty one. '' < 'BR' so 'BR' wins. Non-empty
#     always beats empty. Behaves correctly even if only some batches had
#     a userinfo record for the victim.
#   - SAF(max, UInt8) on presence flags: once a batch sees '1', the merge
#     keeps '1' forever.
#
# Victim_folder is derived by the MV from file_path using the segment-[2]
# split (Khazan archive structure is <channel_wrapper>/<victim>/<content>).
# The extracted_records.victim_folder column itself is currently set to the
# random temp extraction dir name by the pipeline, which does not
# distinguish victims. Fix is pending; MV bypasses by deriving directly.
_VICTIM_PROFILES: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS {db}.victim_profiles
    (
        archive_sha256         FixedString(64),
        victim_folder          String,
        source                 SimpleAggregateFunction(max, LowCardinality(String)),
        country                SimpleAggregateFunction(max, LowCardinality(String)),
        egress_ip              SimpleAggregateFunction(max, String),
        user_name              SimpleAggregateFunction(max, String),
        computer_name          SimpleAggregateFunction(max, String),
        os_version             SimpleAggregateFunction(max, String),
        traffic_affid          SimpleAggregateFunction(max, LowCardinality(String)),
        build_version          SimpleAggregateFunction(max, LowCardinality(String)),
        payload_md5            SimpleAggregateFunction(max, String),
        work_dir               SimpleAggregateFunction(max, String),
        creds_count            SimpleAggregateFunction(sum, UInt32),
        cookies_count          SimpleAggregateFunction(sum, UInt32),
        autofills_count        SimpleAggregateFunction(sum, UInt32),
        history_count          SimpleAggregateFunction(sum, UInt32),
        downloads_count        SimpleAggregateFunction(sum, UInt32),
        processes_count        SimpleAggregateFunction(sum, UInt32),
        software_count         SimpleAggregateFunction(sum, UInt32),
        discord_tokens_count   SimpleAggregateFunction(sum, UInt32),
        steam_tokens_count     SimpleAggregateFunction(sum, UInt32),
        google_refresh_count   SimpleAggregateFunction(sum, UInt32),
        localstorage_jwt_count SimpleAggregateFunction(sum, UInt32),
        wallet_vaults_count    SimpleAggregateFunction(sum, UInt32),
        has_corporate_marker   SimpleAggregateFunction(max, UInt8),
        has_webmail_leak       SimpleAggregateFunction(max, UInt8),
        has_wallet             SimpleAggregateFunction(max, UInt8),
        has_crypter_banner     SimpleAggregateFunction(max, UInt8),
        webmail_identity       SimpleAggregateFunction(max, String),
        first_corporate_marker SimpleAggregateFunction(max, String),
        first_wallet_family    SimpleAggregateFunction(max, LowCardinality(String)),
        INDEX idx_country country TYPE set(0) GRANULARITY 1,
        INDEX idx_affid traffic_affid TYPE set(0) GRANULARITY 1,
        INDEX idx_has_wallet has_wallet TYPE set(0) GRANULARITY 1,
        INDEX idx_has_corporate has_corporate_marker TYPE set(0) GRANULARITY 1
    )
    ENGINE = AggregatingMergeTree
    ORDER BY (archive_sha256, victim_folder)
    {storage_policy_clause}
    """,
    # MV reads only the batch being inserted. Fields the batch does not
    # contribute leave empty strings / zeros which SAF's lexicographic max
    # discards in favour of non-empty values from other batches.
    # victim_folder='' rows (files at the archive root with no victim
    # subdirectory) are filtered out so the UI never shows a phantom "empty
    # victim" row.
    """
    CREATE MATERIALIZED VIEW IF NOT EXISTS {db}.victim_profiles_mv
    TO {db}.victim_profiles AS
    SELECT
        archive_sha256,
        splitByChar('/', file_path)[2] AS victim_folder,
        max(source) AS source,
        max(fields['ui_country']) AS country,
        max(if(fields['ui_egress_ip'] != '', fields['ui_egress_ip'], fields['build_egress_ip'])) AS egress_ip,
        max(coalesce(nullIf(fields['ui_user_name'], ''), nullIf(fields['os_user_name'], ''), nullIf(fields['env_user_name'], ''), '')) AS user_name,
        max(coalesce(nullIf(fields['ui_computer'], ''), nullIf(fields['os_computer_name'], ''), nullIf(fields['env_computer_name'], ''), '')) AS computer_name,
        max(coalesce(nullIf(fields['ui_os'], ''), nullIf(fields['os_version'], ''), '')) AS os_version,
        max(fields['ui_traffic_affid']) AS traffic_affid,
        max(coalesce(nullIf(fields['ui_build_version'], ''), nullIf(fields['build_tag'], ''), '')) AS build_version,
        max(fields['ui_payload_md5']) AS payload_md5,
        max(fields['ui_work_dir']) AS work_dir,
        toUInt32(countIf(rule_id LIKE 'passwords_%')) AS creds_count,
        toUInt32(countIf(rule_id = 'cookies_netscape_tsv')) AS cookies_count,
        toUInt32(countIf(rule_id IN ('autofills_form_value_block', 'autofills_space_delim'))) AS autofills_count,
        toUInt32(countIf(rule_id = 'history_url_title_block')) AS history_count,
        toUInt32(countIf(rule_id = 'download_history_block')) AS downloads_count,
        toUInt32(countIf(rule_id LIKE 'processes_%')) AS processes_count,
        toUInt32(countIf(rule_id = 'software_installed_list')) AS software_count,
        toUInt32(countIf(rule_id = 'discord_tokens_plain')) AS discord_tokens_count,
        toUInt32(countIf(rule_id = 'steam_jwt_tokens')) AS steam_tokens_count,
        toUInt32(countIf(rule_id = 'google_restore_tokens')) AS google_refresh_count,
        toUInt32(countIf(rule_id = 'localstorage_jwt_candidates')) AS localstorage_jwt_count,
        toUInt32(countIf(rule_id LIKE 'wallet_vault_leveldb:%')) AS wallet_vaults_count,
        maxIf(toUInt8(1), rule_id = 'software_corporate_marker') AS has_corporate_marker,
        maxIf(toUInt8(1), rule_id = 'history_webmail_identity') AS has_webmail_leak,
        maxIf(toUInt8(1), rule_id LIKE 'wallet_vault_leveldb:%' OR family = 'exodus_wallet') AS has_wallet,
        maxIf(toUInt8(1), rule_id = 'aware_crypter_banner') AS has_crypter_banner,
        maxIf(fields['webmail_email'], rule_id = 'history_webmail_identity') AS webmail_identity,
        maxIf(fields['corporate_marker'], rule_id = 'software_corporate_marker') AS first_corporate_marker,
        maxIf(family, rule_id LIKE 'wallet_vault_leveldb:%') AS first_wallet_family
    FROM {db}.extracted_records
    WHERE splitByChar('/', file_path)[2] != ''
    GROUP BY archive_sha256, victim_folder
    """,
    # Idempotent backfill with NOT EXISTS gate. First-run on an existing
    # extracted_records populates all historical rows; subsequent calls on
    # each pipeline run are no-ops.
    """
    INSERT INTO {db}.victim_profiles
    SELECT
        archive_sha256,
        splitByChar('/', file_path)[2] AS victim_folder,
        max(source) AS source,
        max(fields['ui_country']) AS country,
        max(if(fields['ui_egress_ip'] != '', fields['ui_egress_ip'], fields['build_egress_ip'])) AS egress_ip,
        max(coalesce(nullIf(fields['ui_user_name'], ''), nullIf(fields['os_user_name'], ''), nullIf(fields['env_user_name'], ''), '')) AS user_name,
        max(coalesce(nullIf(fields['ui_computer'], ''), nullIf(fields['os_computer_name'], ''), nullIf(fields['env_computer_name'], ''), '')) AS computer_name,
        max(coalesce(nullIf(fields['ui_os'], ''), nullIf(fields['os_version'], ''), '')) AS os_version,
        max(fields['ui_traffic_affid']) AS traffic_affid,
        max(coalesce(nullIf(fields['ui_build_version'], ''), nullIf(fields['build_tag'], ''), '')) AS build_version,
        max(fields['ui_payload_md5']) AS payload_md5,
        max(fields['ui_work_dir']) AS work_dir,
        toUInt32(countIf(rule_id LIKE 'passwords_%')) AS creds_count,
        toUInt32(countIf(rule_id = 'cookies_netscape_tsv')) AS cookies_count,
        toUInt32(countIf(rule_id IN ('autofills_form_value_block', 'autofills_space_delim'))) AS autofills_count,
        toUInt32(countIf(rule_id = 'history_url_title_block')) AS history_count,
        toUInt32(countIf(rule_id = 'download_history_block')) AS downloads_count,
        toUInt32(countIf(rule_id LIKE 'processes_%')) AS processes_count,
        toUInt32(countIf(rule_id = 'software_installed_list')) AS software_count,
        toUInt32(countIf(rule_id = 'discord_tokens_plain')) AS discord_tokens_count,
        toUInt32(countIf(rule_id = 'steam_jwt_tokens')) AS steam_tokens_count,
        toUInt32(countIf(rule_id = 'google_restore_tokens')) AS google_refresh_count,
        toUInt32(countIf(rule_id = 'localstorage_jwt_candidates')) AS localstorage_jwt_count,
        toUInt32(countIf(rule_id LIKE 'wallet_vault_leveldb:%')) AS wallet_vaults_count,
        maxIf(toUInt8(1), rule_id = 'software_corporate_marker') AS has_corporate_marker,
        maxIf(toUInt8(1), rule_id = 'history_webmail_identity') AS has_webmail_leak,
        maxIf(toUInt8(1), rule_id LIKE 'wallet_vault_leveldb:%' OR family = 'exodus_wallet') AS has_wallet,
        maxIf(toUInt8(1), rule_id = 'aware_crypter_banner') AS has_crypter_banner,
        maxIf(fields['webmail_email'], rule_id = 'history_webmail_identity') AS webmail_identity,
        maxIf(fields['corporate_marker'], rule_id = 'software_corporate_marker') AS first_corporate_marker,
        maxIf(family, rule_id LIKE 'wallet_vault_leveldb:%') AS first_wallet_family
    FROM {db}.extracted_records
    WHERE splitByChar('/', file_path)[2] != ''
      AND NOT EXISTS (SELECT 1 FROM {db}.victim_profiles)
    GROUP BY archive_sha256, victim_folder
    """,
)


class ClickHouseRecordsSink:
    """Connection + schema + batched insert for ``<db>.extracted_records``.

    Same shape as ``ClickHouseCredsSink`` so the pipeline can init +
    insert_rows symmetrically. Rows are tuples positional with
    ``_RECORDS_COLUMNS`` (fields being a Python ``dict[str, str]`` which
    clickhouse-connect serialises as a Map on insert).
    """

    def __init__(self) -> None:
        self._db = clickhouse_db()
        self._client: Client | None = None

    def _connect(self) -> Client:
        if self._client is None:
            self._client = get_clickhouse_client()
        return self._client

    def ensure_schema(self) -> None:
        client = self._connect()
        client.command(_CREATE_DB.format(db=self._db))
        client.command(
            _RECORDS_CREATE.format(
                db=self._db,
                storage_policy_clause=_storage_policy_clause(),
            )
        )
        # v1.3.3 per-victim profile roll-up (table + MV + idempotent backfill).
        for stmt in _VICTIM_PROFILES:
            client.command(
                stmt.format(db=self._db, storage_policy_clause=_storage_policy_clause())
            )

    def insert_rows(self, rows: Iterable[list[Any]]) -> int:
        batch: list[list[Any]] = list(rows)
        if not batch:
            return 0
        self._connect().insert(
            f"{self._db}.extracted_records", batch, column_names=_RECORDS_COLUMNS,
        )
        return len(batch)

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None


# v1.2.6 observability side channel. One row per file in every per-victim folder
# of every archive, so operators can answer "what files do we SEE that we are
# not parsing" from a SQL query instead of spelunking blobs by hand. The table
# is intentionally thin (no per-line counts; v1.3.0 adds those when the Go
# extractor is touched for the rule engine). ReplacingMergeTree collapses
# re-scans of the same file in the same archive on dedup.
_FILE_AUDIT_CREATE = """
CREATE TABLE IF NOT EXISTS {db}.file_audit
(
    archive_sha256      FixedString(64),
    rel_path            String,
    filename            String,
    size_bytes          UInt64,
    file_sha256         FixedString(64),
    heuristic_kind      LowCardinality(String),
    extractor_touched   UInt8    DEFAULT 0,
    rows_emitted        UInt32   DEFAULT 0,
    approx_banner_hits  UInt32   DEFAULT 0,
    approx_null_pw_hits UInt32   DEFAULT 0,
    sample_head         String,
    parsed_at           DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(parsed_at)
ORDER BY (archive_sha256, rel_path)
{storage_policy_clause}
"""

_FILE_AUDIT_COLUMNS = [
    "archive_sha256",
    "rel_path",
    "filename",
    "size_bytes",
    "file_sha256",
    "heuristic_kind",
    "extractor_touched",
    "rows_emitted",
    "approx_banner_hits",
    "approx_null_pw_hits",
    "sample_head",
]

# v1.2.7 schema evolution for file_audit: pre-aggregated roll-up tables + the
# materialized views that keep them current on every INSERT into file_audit, plus
# the skip indexes that accelerate /audit/search substring queries. Taking the
# migrate pill now so the API endpoints stay sub-second regardless of corpus size.
#
# Rationale (per scope discussion with operator, v1.2.7 cut):
#   * /coverage and /unknown are GROUP BY queries whose cost scales with the full
#     file_audit row count, not the number of distinct groups. Pre-aggregating
#     into AggregatingMergeTree tables flips the query cost from O(rows in
#     file_audit) to O(rows in the roll-up), typically 2-4 orders of magnitude
#     smaller.
#   * SimpleAggregateFunction is used for the commutative + associative aggregates
#     (sum/min/max) so the Python reader selects values directly, no *Merge()
#     wrappers; AggregateFunction is used for uniqExact + any which need state.
#   * POPULATE on the first MATERIALIZED VIEW creation backfills the existing
#     ~32k rows on prod (one-shot, blocks file_audit INSERTs briefly, acceptable).
#   * Skip indexes on sample_head (ngram) + rel_path (token) make /audit/search
#     prune granules that provably don't contain the substring term.
#
# Every statement is CREATE ... IF NOT EXISTS / ALTER ... ADD INDEX IF NOT EXISTS
# so ensure_schema() can be called on every archive processed without side
# effects beyond the first invocation.
_FILE_AUDIT_V127: tuple[str, ...] = (
    # Per-archive coverage: one row per (archive_sha256), autosums on merge.
    # Numeric counters are SimpleAggregateFunction(sum, ...) so a SELECT
    # against this table does not need *Merge() wrappers for them. first/last
    # timestamps use SimpleAggregateFunction(min|max, DateTime) which also
    # expose the stored value directly.
    """
    CREATE TABLE IF NOT EXISTS {db}.file_audit_per_archive
    (
        archive_sha256 FixedString(64),
        total_files    SimpleAggregateFunction(sum, UInt64),
        parsed_files   SimpleAggregateFunction(sum, UInt64),
        unknown_files  SimpleAggregateFunction(sum, UInt64),
        first_seen_at  SimpleAggregateFunction(min, DateTime),
        last_seen_at   SimpleAggregateFunction(max, DateTime)
    )
    ENGINE = AggregatingMergeTree
    ORDER BY archive_sha256
    """,
    # Write-through MV. POPULATE runs the SELECT against existing rows at CREATE
    # time; from then on every new INSERT into file_audit fires this SELECT and
    # writes a one-row delta into file_audit_per_archive (merged by CH later).
    #
    # The unknown_files predicate mirrors the /audit/unknown endpoint: files the
    # extractor did NOT touch, excluding empty/binary (operator cannot write a
    # rule for those). Keep in sync with FileAuditReader.unknown()'s WHERE.
    # CH 24.x refuses TO [target] + POPULATE together (code 62 SYNTAX_ERROR).
    # Create the MV without POPULATE, then backfill historical rows via an
    # idempotent INSERT guarded by "target is empty" (below). New rows are
    # handled by the MV going forward.
    """
    CREATE MATERIALIZED VIEW IF NOT EXISTS {db}.file_audit_per_archive_mv
    TO {db}.file_audit_per_archive AS
    SELECT
        archive_sha256,
        toUInt64(1) AS total_files,
        toUInt64(extractor_touched) AS parsed_files,
        toUInt64(extractor_touched = 0
                 AND heuristic_kind NOT IN ('empty','binary')) AS unknown_files,
        parsed_at AS first_seen_at,
        parsed_at AS last_seen_at
    FROM {db}.file_audit
    """,
    # One-shot backfill for the per-archive roll-up. The nested EXISTS gate makes
    # this a no-op once the target has any row -- safe to re-run on every
    # ensure_schema() call. Runs AFTER the MV CREATE above so there's no race
    # window where the MV is live but history is missing: either the target is
    # empty and we fill it, or it has at least one row (from either backfill or
    # a prior insert) and we skip.
    """
    INSERT INTO {db}.file_audit_per_archive
    SELECT
        archive_sha256,
        toUInt64(1) AS total_files,
        toUInt64(extractor_touched) AS parsed_files,
        toUInt64(extractor_touched = 0
                 AND heuristic_kind NOT IN ('empty','binary')) AS unknown_files,
        parsed_at AS first_seen_at,
        parsed_at AS last_seen_at
    FROM {db}.file_audit
    WHERE NOT EXISTS (SELECT 1 FROM {db}.file_audit_per_archive)
    """,
    # Per (filename, heuristic_kind) aggregation for the unknown-files workbench.
    # archive_count + sample_head need stateful aggregates (uniqExact + any), so
    # we use AggregateFunction with *State/*Merge rather than SimpleAggregateFunction.
    """
    CREATE TABLE IF NOT EXISTS {db}.file_audit_per_unknown_file
    (
        filename             String,
        heuristic_kind       LowCardinality(String),
        occurrences          SimpleAggregateFunction(sum, UInt64),
        archive_count_state  AggregateFunction(uniqExact, FixedString(64)),
        sample_head_state    AggregateFunction(any, String)
    )
    ENGINE = AggregatingMergeTree
    ORDER BY (filename, heuristic_kind)
    """,
    # Same POPULATE-vs-TO constraint as the per_archive MV above.
    """
    CREATE MATERIALIZED VIEW IF NOT EXISTS {db}.file_audit_per_unknown_file_mv
    TO {db}.file_audit_per_unknown_file AS
    SELECT
        filename,
        heuristic_kind,
        toUInt64(1) AS occurrences,
        uniqExactState(archive_sha256) AS archive_count_state,
        anyState(sample_head) AS sample_head_state
    FROM {db}.file_audit
    WHERE extractor_touched = 0 AND heuristic_kind NOT IN ('empty','binary')
    GROUP BY filename, heuristic_kind
    """,
    # Idempotent backfill for the per-unknown-file roll-up (same gate pattern).
    """
    INSERT INTO {db}.file_audit_per_unknown_file
    SELECT
        filename,
        heuristic_kind,
        toUInt64(1) AS occurrences,
        uniqExactState(archive_sha256) AS archive_count_state,
        anyState(sample_head) AS sample_head_state
    FROM {db}.file_audit
    WHERE extractor_touched = 0 AND heuristic_kind NOT IN ('empty','binary')
      AND NOT EXISTS (SELECT 1 FROM {db}.file_audit_per_unknown_file)
    GROUP BY filename, heuristic_kind
    """,
    # Skip indexes for /audit/search. 4-gram over sample_head covers short
    # identifier searches (hostnames, UUIDs, usernames); tokenbf on rel_path
    # accelerates "which files live under /path/foo/..." style substring hits.
    # ngrambf_v1(n, size_bytes, hashes, seed) -- 4-gram, 64 KiB bloom filter per
    # granule, 3 hashes, default seed. tokenbf_v1(size_bytes, hashes, seed).
    "ALTER TABLE {db}.file_audit ADD INDEX IF NOT EXISTS "
    "sample_head_ngram sample_head TYPE ngrambf_v1(4, 65536, 3, 0) GRANULARITY 1",
    "ALTER TABLE {db}.file_audit ADD INDEX IF NOT EXISTS "
    "rel_path_tokens rel_path TYPE tokenbf_v1(16384, 3, 0) GRANULARITY 1",
    # v1.3.3 per-victim column. Derived from the second path segment
    # (Khazan archive structure is <channel_wrapper>/<victim>/<content>).
    # MATERIALIZED columns compute on INSERT and are NULL-safe on existing
    # rows until ALTER TABLE ... MATERIALIZE COLUMN runs (the next DDL).
    # Skip index enables cheap (archive_sha256, victim_folder) filters for
    # the FE drawer's file-tree query.
    "ALTER TABLE {db}.file_audit ADD COLUMN IF NOT EXISTS "
    "victim_folder String MATERIALIZED splitByChar('/', rel_path)[2]",
    "ALTER TABLE {db}.file_audit MATERIALIZE COLUMN victim_folder",
    "ALTER TABLE {db}.file_audit ADD INDEX IF NOT EXISTS "
    "victim_folder_set victim_folder TYPE set(0) GRANULARITY 1",
)


class FileAuditSink:
    """CH sink for the file_audit observability table. Mirrors
    ``ClickHouseCredsSink`` shape so the pipeline can init + call insert_rows
    the same way. Separate class so a CH misconfig on file_audit never breaks
    the credential insert path."""

    def __init__(self) -> None:
        self._db = clickhouse_db()
        self._client: Client | None = None

    def _connect(self) -> Client:
        if self._client is None:
            self._client = get_clickhouse_client()
        return self._client

    def ensure_schema(self) -> None:
        """Create database + file_audit table + the v1.2.7 pre-aggregated
        tables + their materialized views + the search skip indexes. All
        statements are idempotent so an upgrade from v1.2.6 is a no-op on
        existing clusters and a one-shot create on fresh ones."""
        client = self._connect()
        client.command(_CREATE_DB.format(db=self._db))
        client.command(
            _FILE_AUDIT_CREATE.format(
                db=self._db,
                storage_policy_clause=_storage_policy_clause(),
            )
        )
        for stmt in _FILE_AUDIT_V127:
            client.command(stmt.format(db=self._db))

    def insert_rows(self, rows: Iterable[list[Any]]) -> int:
        batch: list[list[Any]] = list(rows)
        if not batch:
            return 0
        self._connect().insert(
            f"{self._db}.file_audit", batch, column_names=_FILE_AUDIT_COLUMNS
        )
        return len(batch)

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None


__all__ = [
    "ClickHouseCredsSink",
    "FileAuditSink",
    "clickhouse_db",
    "get_clickhouse_client",
]
