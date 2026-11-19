# SPDX-License-Identifier: AGPL-3.0-or-later
"""ClickHouse sinks for the stealer corpus.

Thin wrapper over clickhouse-connect (HTTP). Owns two write paths:

- ``ClickHouseRecordsSink`` + ``_RECORDS_CREATE``: gotractor's
  ``stealer.extracted_records`` landing table (dedup key is a hash of
  the fields Map). The primary corpus.
- ``FileAuditSink`` + ``_FILE_AUDIT_CREATE`` + its pre-aggregate MVs:
  the per-file observability side channel.

clickhouse-connect is an OPTIONAL dep shipped in the stealer profile
image, so it's imported lazily; the core stack never needs it.

Config via env: ``EYENET_CLICKHOUSE_HOST`` (default "clickhouse"),
``_PORT`` (8123), ``_USER`` (default "default"), ``_PASSWORD`` (default
""), ``_DB`` (default "stealer").
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

    from clickhouse_connect.driver.client import Client

_CREATE_DB = "CREATE DATABASE IF NOT EXISTS {db}"

# The ulpextract-era <db>.creds DDL + its _COLUMNS / _ALTER_TABLE chain
# were removed with the rest of the ulpextract machinery. StealerCredsReader
# now reads from extracted_records via CH's URL functions; existing
# <db>.creds rows stay on disk as a cold tombstone until the operator
# runs DROP TABLE <db>.creds by hand.


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
    """A clickhouse-connect sync client from EYENET_CLICKHOUSE_* env. Used by the
    creds sink (processor is a pure sync pipeline) and the schema DDL path."""
    import clickhouse_connect  # noqa: PLC0415 - dep present in core + stealer images

    return clickhouse_connect.get_client(
        host=os.environ.get("EYENET_CLICKHOUSE_HOST", "clickhouse"),
        port=int(os.environ.get("EYENET_CLICKHOUSE_PORT", "8123")),
        username=os.environ.get("EYENET_CLICKHOUSE_USER", "default"),
        password=os.environ.get("EYENET_CLICKHOUSE_PASSWORD", ""),
    )


async def get_async_clickhouse_client() -> Any:
    """Async clickhouse-connect client for the API read path. Built-in connection
    pool, every call is awaitable, event loop never blocks. Swap for the sync one
    in any reader the API serves concurrently; keep the sync one for the
    processor's single-threaded pipeline. Returns Any because clickhouse-connect
    does not export a public AsyncClient type under a stable path yet."""
    import clickhouse_connect  # noqa: PLC0415

    return await clickhouse_connect.get_async_client(
        host=os.environ.get("EYENET_CLICKHOUSE_HOST", "clickhouse"),
        port=int(os.environ.get("EYENET_CLICKHOUSE_PORT", "8123")),
        username=os.environ.get("EYENET_CLICKHOUSE_USER", "default"),
        password=os.environ.get("EYENET_CLICKHOUSE_PASSWORD", ""),
    )


# gotractor landing table. One row per EXTRACTED RECORD from the
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
    "archive_sha256",
    "source",
    "victim_folder",
    "file_path",
    "rule_id",
    "family",
    "fields",
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
#   - SAF(sum, UInt64) on counts: batches add together on background merge.
#     Widened from UInt32 in v1.3.4.1: a 110k-cred archive overflows the Int32
#     range when the MV re-materializes against a historical backfill, and
#     ClickHouse 24 refuses the INSERT with "Incompatible data types between
#     aggregate function 'sum' which returns UInt64 and column storage type
#     UInt32."
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
        creds_count            SimpleAggregateFunction(sum, UInt64),
        cookies_count          SimpleAggregateFunction(sum, UInt64),
        autofills_count        SimpleAggregateFunction(sum, UInt64),
        history_count          SimpleAggregateFunction(sum, UInt64),
        downloads_count        SimpleAggregateFunction(sum, UInt64),
        processes_count        SimpleAggregateFunction(sum, UInt64),
        software_count         SimpleAggregateFunction(sum, UInt64),
        discord_tokens_count   SimpleAggregateFunction(sum, UInt64),
        steam_tokens_count     SimpleAggregateFunction(sum, UInt64),
        google_refresh_count   SimpleAggregateFunction(sum, UInt64),
        localstorage_jwt_count SimpleAggregateFunction(sum, UInt64),
        wallet_vaults_count    SimpleAggregateFunction(sum, UInt64),
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
        toUInt64(countIf(family IN ('browser_passwords','combolist','windows_credentials','json_v2'))) AS creds_count,
        toUInt64(countIf(family IN ('cookies','victim_cookies'))) AS cookies_count,
        toUInt64(countIf(family = 'victim_autofills')) AS autofills_count,
        toUInt64(countIf(family = 'victim_history')) AS history_count,
        toUInt64(countIf(family = 'victim_downloads')) AS downloads_count,
        toUInt64(countIf(family = 'victim_processes')) AS processes_count,
        toUInt64(countIf(family = 'victim_software')) AS software_count,
        toUInt64(countIf(family = 'discord_tokens')) AS discord_tokens_count,
        toUInt64(countIf(family = 'steam_accounts')) AS steam_tokens_count,
        toUInt64(countIf(family = 'google_oauth_tokens')) AS google_refresh_count,
        toUInt64(countIf(rule_id = 'localstorage_jwt_candidates')) AS localstorage_jwt_count,
        toUInt64(countIf(rule_id LIKE 'wallet_vault_leveldb:%')) AS wallet_vaults_count,
        maxIf(toUInt8(1), rule_id = 'software_corporate_marker') AS has_corporate_marker,
        maxIf(toUInt8(1), rule_id = 'history_webmail_identity') AS has_webmail_leak,
        maxIf(toUInt8(1), rule_id LIKE 'wallet_vault_leveldb:%' OR family = 'exodus_wallet') AS has_wallet,
        maxIf(toUInt8(1), family = 'aware_crypter') AS has_crypter_banner,
        maxIf(fields['webmail_email'], rule_id = 'history_webmail_identity') AS webmail_identity,
        maxIf(fields['corporate_marker'], rule_id = 'software_corporate_marker') AS first_corporate_marker,
        maxIf(family, rule_id LIKE 'wallet_vault_leveldb:%') AS first_wallet_family
    FROM {db}.extracted_records
    WHERE splitByChar('/', file_path)[2] != ''
    GROUP BY archive_sha256, victim_folder
    """,
    # Idempotent backfill with NOT EXISTS gate. First-run on an existing
    # extracted_records populates all historical rows; subsequent calls on
    # each pipeline run are no-ops. v1.3.1: also fires after the one-shot
    # repair (see _repair_victim_profiles_if_stale) rebuilds the table.
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
        toUInt64(countIf(family IN ('browser_passwords','combolist','windows_credentials','json_v2'))) AS creds_count,
        toUInt64(countIf(family IN ('cookies','victim_cookies'))) AS cookies_count,
        toUInt64(countIf(family = 'victim_autofills')) AS autofills_count,
        toUInt64(countIf(family = 'victim_history')) AS history_count,
        toUInt64(countIf(family = 'victim_downloads')) AS downloads_count,
        toUInt64(countIf(family = 'victim_processes')) AS processes_count,
        toUInt64(countIf(family = 'victim_software')) AS software_count,
        toUInt64(countIf(family = 'discord_tokens')) AS discord_tokens_count,
        toUInt64(countIf(family = 'steam_accounts')) AS steam_tokens_count,
        toUInt64(countIf(family = 'google_oauth_tokens')) AS google_refresh_count,
        toUInt64(countIf(rule_id = 'localstorage_jwt_candidates')) AS localstorage_jwt_count,
        toUInt64(countIf(rule_id LIKE 'wallet_vault_leveldb:%')) AS wallet_vaults_count,
        maxIf(toUInt8(1), rule_id = 'software_corporate_marker') AS has_corporate_marker,
        maxIf(toUInt8(1), rule_id = 'history_webmail_identity') AS has_webmail_leak,
        maxIf(toUInt8(1), rule_id LIKE 'wallet_vault_leveldb:%' OR family = 'exodus_wallet') AS has_wallet,
        maxIf(toUInt8(1), family = 'aware_crypter') AS has_crypter_banner,
        maxIf(fields['webmail_email'], rule_id = 'history_webmail_identity') AS webmail_identity,
        maxIf(fields['corporate_marker'], rule_id = 'software_corporate_marker') AS first_corporate_marker,
        maxIf(family, rule_id LIKE 'wallet_vault_leveldb:%') AS first_wallet_family
    FROM {db}.extracted_records
    WHERE splitByChar('/', file_path)[2] != ''
      AND NOT EXISTS (SELECT 1 FROM {db}.victim_profiles)
    GROUP BY archive_sha256, victim_folder
    """,
)


# v1.3.1 one-shot repair sentinel. The pre-1.3.1 MV body counted creds by
# `rule_id LIKE 'passwords_%'` (never matches: real rule_ids are
# passwords_block_title, combolist_*, credentials_windows, etc.) and
# cookies by `rule_id = 'cookies_netscape_tsv'` (misses the bulk
# netscape_cookies hits). Prod was showing 0 creds / 0 cookies on
# 3.6M-row extracted_records. The new MV keys off `family` (stable,
# catalog-defined). This string is the sentinel we grep in
# system.tables.create_table_query to decide whether to force-rebuild.
_VICTIM_PROFILES_STALE_SENTINEL = "rule_id LIKE 'passwords_"


# v1.3.1 /stats pre-aggregation. Before: GET /v1/stealer/stats ran 4 FULL
# scans of extracted_records with FINAL, uniqExact over 3.6M rows per
# call. The dashboard polls it and prod CPU paid for it each time. After:
# four AggregatingMergeTree rollups fired on every INSERT into
# extracted_records. Reader queries sum() + uniqMerge() on tiny rollup
# tables; response is O(1)-ish regardless of corpus size.
#
# The four rollups mirror the shape of the /stats response:
#   - stats_rollup_totals: single row ('all') holding sum(total_creds) +
#     uniq HLL sketches for unique_creds + distinct_hosts.
#   - stats_rollup_scheme:  per-scheme sum. Tiny cardinality (http/https
#     +/android).
#   - stats_rollup_tld:     per-tld sum. Hundreds of keys.
#   - stats_rollup_host:    per-host sum. Tens of thousands at prod scale.
#
# The HOST/SCHEME/TLD expressions must stay in lock-step with the Python
# reader (eyenet/stealer/query.py StealerCredsReader._{HOST,SCHEME,TLD}_EXPR)
# so pre-rollup and post-rollup buckets agree. If you change one, change
# the other AND bump _STATS_ROLLUP_STALE_SENTINEL to force rebuild.
_CRED_FAMS_LITERAL = "('browser_passwords', 'windows_credentials', 'firefox_logins', 'combolist')"
_HOST_EXPR_DDL = (
    "lower(coalesce("
    "nullIf(domain(fields['url']), ''), "
    "nullIf(domain(fields['host']), ''), "
    "nullIf(fields['host'], ''), ''))"
)
_SCHEME_EXPR_DDL = (
    "lower(coalesce(nullIf(fields['scheme'], ''), nullIf(protocol(fields['url']), ''), ''))"
)
_TLD_EXPR_DDL = (
    "coalesce("
    "nullIf(fields['tld'], ''), "
    "nullIf(topLevelDomain(fields['url']), ''), "
    "nullIf(topLevelDomain(fields['host']), ''), '')"
)
_STATS_WHERE = (
    f"family IN {_CRED_FAMS_LITERAL} AND (notEmpty(fields['url']) OR notEmpty(fields['host']))"
)

# Each DDL below is a static template; _CRED_FAMS_LITERAL / _HOST_EXPR_DDL etc.
# are MODULE constants (no external input) and _STATS_WHERE is composed from
# them. ruff S608 flags f-strings that interpolate into SQL; the "variables"
# here are compile-time literals the module owns, so per-f-string noqa.
_STATS_ROLLUP_TOTALS_MV = f"""
    CREATE MATERIALIZED VIEW IF NOT EXISTS {{db}}.stats_rollup_totals_mv
    TO {{db}}.stats_rollup_totals AS
    SELECT
        'all' AS bucket,
        toUInt64(count()) AS total_creds,
        uniqState(({_HOST_EXPR_DDL}, fields['login'], fields['password'])) AS unique_creds,
        uniqState({_HOST_EXPR_DDL}) AS distinct_hosts
    FROM {{db}}.extracted_records
    WHERE {_STATS_WHERE}
    GROUP BY bucket
    """  # noqa: S608  # nosec B608
_STATS_ROLLUP_SCHEME_MV = f"""
    CREATE MATERIALIZED VIEW IF NOT EXISTS {{db}}.stats_rollup_scheme_mv
    TO {{db}}.stats_rollup_scheme AS
    SELECT
        {_SCHEME_EXPR_DDL} AS scheme,
        toUInt64(count()) AS cnt
    FROM {{db}}.extracted_records
    WHERE {_STATS_WHERE} AND notEmpty({_SCHEME_EXPR_DDL})
    GROUP BY scheme
    """  # noqa: S608  # nosec B608
_STATS_ROLLUP_TLD_MV = f"""
    CREATE MATERIALIZED VIEW IF NOT EXISTS {{db}}.stats_rollup_tld_mv
    TO {{db}}.stats_rollup_tld AS
    SELECT
        {_TLD_EXPR_DDL} AS tld,
        toUInt64(count()) AS cnt
    FROM {{db}}.extracted_records
    WHERE {_STATS_WHERE} AND notEmpty({_TLD_EXPR_DDL})
    GROUP BY tld
    """  # noqa: S608  # nosec B608
_STATS_ROLLUP_HOST_MV = f"""
    CREATE MATERIALIZED VIEW IF NOT EXISTS {{db}}.stats_rollup_host_mv
    TO {{db}}.stats_rollup_host AS
    SELECT
        {_HOST_EXPR_DDL} AS host,
        toUInt64(count()) AS cnt
    FROM {{db}}.extracted_records
    WHERE {_STATS_WHERE} AND notEmpty({_HOST_EXPR_DDL})
    GROUP BY host
    """  # noqa: S608  # nosec B608
_STATS_ROLLUP_TOTALS_BACKFILL = f"""
    INSERT INTO {{db}}.stats_rollup_totals
    SELECT
        'all' AS bucket,
        toUInt64(count()) AS total_creds,
        uniqState(({_HOST_EXPR_DDL}, fields['login'], fields['password'])) AS unique_creds,
        uniqState({_HOST_EXPR_DDL}) AS distinct_hosts
    FROM {{db}}.extracted_records
    WHERE {_STATS_WHERE}
      AND NOT EXISTS (SELECT 1 FROM {{db}}.stats_rollup_totals)
    GROUP BY bucket
    """  # noqa: S608  # nosec B608
_STATS_ROLLUP_SCHEME_BACKFILL = f"""
    INSERT INTO {{db}}.stats_rollup_scheme
    SELECT {_SCHEME_EXPR_DDL} AS scheme, toUInt64(count()) AS cnt
    FROM {{db}}.extracted_records
    WHERE {_STATS_WHERE} AND notEmpty({_SCHEME_EXPR_DDL})
      AND NOT EXISTS (SELECT 1 FROM {{db}}.stats_rollup_scheme)
    GROUP BY scheme
    """  # noqa: S608  # nosec B608
_STATS_ROLLUP_TLD_BACKFILL = f"""
    INSERT INTO {{db}}.stats_rollup_tld
    SELECT {_TLD_EXPR_DDL} AS tld, toUInt64(count()) AS cnt
    FROM {{db}}.extracted_records
    WHERE {_STATS_WHERE} AND notEmpty({_TLD_EXPR_DDL})
      AND NOT EXISTS (SELECT 1 FROM {{db}}.stats_rollup_tld)
    GROUP BY tld
    """  # noqa: S608  # nosec B608
_STATS_ROLLUP_HOST_BACKFILL = f"""
    INSERT INTO {{db}}.stats_rollup_host
    SELECT {_HOST_EXPR_DDL} AS host, toUInt64(count()) AS cnt
    FROM {{db}}.extracted_records
    WHERE {_STATS_WHERE} AND notEmpty({_HOST_EXPR_DDL})
      AND NOT EXISTS (SELECT 1 FROM {{db}}.stats_rollup_host)
    GROUP BY host
    """  # noqa: S608  # nosec B608

_STATS_ROLLUP: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS {db}.stats_rollup_totals
    (
        bucket         LowCardinality(String),
        total_creds    SimpleAggregateFunction(sum, UInt64),
        unique_creds   AggregateFunction(uniq, Tuple(String, String, String)),
        distinct_hosts AggregateFunction(uniq, String)
    )
    ENGINE = AggregatingMergeTree
    ORDER BY bucket
    {storage_policy_clause}
    """,
    _STATS_ROLLUP_TOTALS_MV,
    """
    CREATE TABLE IF NOT EXISTS {db}.stats_rollup_scheme
    (
        scheme LowCardinality(String),
        cnt    SimpleAggregateFunction(sum, UInt64)
    )
    ENGINE = AggregatingMergeTree
    ORDER BY scheme
    {storage_policy_clause}
    """,
    _STATS_ROLLUP_SCHEME_MV,
    """
    CREATE TABLE IF NOT EXISTS {db}.stats_rollup_tld
    (
        tld LowCardinality(String),
        cnt SimpleAggregateFunction(sum, UInt64)
    )
    ENGINE = AggregatingMergeTree
    ORDER BY tld
    {storage_policy_clause}
    """,
    _STATS_ROLLUP_TLD_MV,
    """
    CREATE TABLE IF NOT EXISTS {db}.stats_rollup_host
    (
        host String,
        cnt  SimpleAggregateFunction(sum, UInt64)
    )
    ENGINE = AggregatingMergeTree
    ORDER BY host
    {storage_policy_clause}
    """,
    _STATS_ROLLUP_HOST_MV,
    # One-shot backfill: NOT EXISTS gate so each only fires on the first
    # ensure_schema() call against an existing corpus.
    _STATS_ROLLUP_TOTALS_BACKFILL,
    _STATS_ROLLUP_SCHEME_BACKFILL,
    _STATS_ROLLUP_TLD_BACKFILL,
    _STATS_ROLLUP_HOST_BACKFILL,
)


# v1.3.1 parse-failures acceleration. GET /v1/stealer/failures was doing
# a LEFT JOIN against a FULL scan of extracted_records (3.6M rows FINAL,
# GROUP BY file_path) just to know which files had at least one record.
# Observed 4.2s wall time for a 25-row page on prod. Fix: maintain a
# tiny ReplacingMergeTree of the DISTINCT file_paths that have ever
# emitted an extracted record. The reader anti-joins against this
# instead of the raw records table.
_EXTRACTED_PATHS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS {db}.extracted_file_paths
    (
        file_path String
    )
    ENGINE = ReplacingMergeTree
    ORDER BY file_path
    {storage_policy_clause}
    """,
    # MV fires on every INSERT into extracted_records. It writes every
    # row's file_path; ReplacingMergeTree collapses dupes on background
    # merge. Query-time dedup is handled by SELECT DISTINCT (cheap).
    """
    CREATE MATERIALIZED VIEW IF NOT EXISTS {db}.extracted_file_paths_mv
    TO {db}.extracted_file_paths AS
    SELECT file_path
    FROM {db}.extracted_records
    """,
    # One-shot backfill. NOT EXISTS gate so this only fires on the first
    # ensure_schema() call against an existing corpus.
    """
    INSERT INTO {db}.extracted_file_paths
    SELECT DISTINCT file_path
    FROM {db}.extracted_records
    WHERE NOT EXISTS (SELECT 1 FROM {db}.extracted_file_paths)
    """,
    # v1.3.1 per-archive per-file row counts. Backs file_tree() and the
    # per-victim coverage computation. Before: both scanned extracted_records
    # FINAL + GROUP BY file_path for ONE archive, which is still O(N) because
    # the sort key is not (archive, file_path). After: a tiny
    # AggregatingMergeTree keyed on exactly that tuple, so a per-archive
    # lookup is a direct index seek.
    """
    CREATE TABLE IF NOT EXISTS {db}.extracted_rows_per_file
    (
        archive_sha256 FixedString(64),
        file_path      String,
        cnt            SimpleAggregateFunction(sum, UInt64)
    )
    ENGINE = AggregatingMergeTree
    ORDER BY (archive_sha256, file_path)
    {storage_policy_clause}
    """,
    """
    CREATE MATERIALIZED VIEW IF NOT EXISTS {db}.extracted_rows_per_file_mv
    TO {db}.extracted_rows_per_file AS
    SELECT
        archive_sha256,
        file_path,
        toUInt64(count()) AS cnt
    FROM {db}.extracted_records
    GROUP BY archive_sha256, file_path
    """,
    """
    INSERT INTO {db}.extracted_rows_per_file
    SELECT archive_sha256, file_path, toUInt64(count()) AS cnt
    FROM {db}.extracted_records
    WHERE NOT EXISTS (SELECT 1 FROM {db}.extracted_rows_per_file)
    GROUP BY archive_sha256, file_path
    """,
    # v1.3.1 per-victim rule-id set. Backs the artifact drawer's
    # fired_rule_ids resolution (which feeds the MITRE ATT&CK technique
    # list). Before: SELECT DISTINCT rule_id FROM extracted_records FINAL
    # WHERE archive = X AND splitByChar('/', file_path)[2] = Y was a full
    # scan because splitByChar is not indexable. After: ReplacingMergeTree
    # keyed on (archive, victim_folder, rule_id); lookup is an index seek.
    """
    CREATE TABLE IF NOT EXISTS {db}.extracted_rules_per_victim
    (
        archive_sha256 FixedString(64),
        victim_folder  String,
        rule_id        LowCardinality(String)
    )
    ENGINE = ReplacingMergeTree
    ORDER BY (archive_sha256, victim_folder, rule_id)
    {storage_policy_clause}
    """,
    """
    CREATE MATERIALIZED VIEW IF NOT EXISTS {db}.extracted_rules_per_victim_mv
    TO {db}.extracted_rules_per_victim AS
    SELECT
        archive_sha256,
        splitByChar('/', file_path)[2] AS victim_folder,
        rule_id
    FROM {db}.extracted_records
    WHERE splitByChar('/', file_path)[2] != ''
    """,
    """
    INSERT INTO {db}.extracted_rules_per_victim
    SELECT
        archive_sha256,
        splitByChar('/', file_path)[2] AS victim_folder,
        rule_id
    FROM {db}.extracted_records
    WHERE splitByChar('/', file_path)[2] != ''
      AND NOT EXISTS (SELECT 1 FROM {db}.extracted_rules_per_victim)
    GROUP BY archive_sha256, victim_folder, rule_id
    """,
    # v1.3.1 per-victim records index. Backs the artifact drawer's
    # Credentials / Cookies / System tabs via StealerCredsReader.records().
    # Before: WHERE archive=X AND splitByChar('/', file_path)[2]=Y scanned
    # the archive's entire extracted_records slice because splitByChar is
    # not indexable, 1s per query x 2 queries (count + page) in parallel
    # = 2s observed. After: ORDER BY (archive, victim_folder, rule_id,
    # file_path) makes the common filter a direct index seek. Full row
    # payload duplicated so the drawer's rule_id / family / file_path /
    # fields read is self-contained.
    """
    CREATE TABLE IF NOT EXISTS {db}.extracted_records_by_victim
    (
        archive_sha256 FixedString(64),
        victim_folder  String,
        rule_id        LowCardinality(String),
        family         LowCardinality(String),
        file_path      String,
        fields         Map(String, String),
        ingested_at    DateTime DEFAULT now()
    )
    ENGINE = ReplacingMergeTree(ingested_at)
    ORDER BY (archive_sha256, victim_folder, rule_id, file_path, cityHash64(toString(fields)))
    {storage_policy_clause}
    """,
    """
    CREATE MATERIALIZED VIEW IF NOT EXISTS {db}.extracted_records_by_victim_mv
    TO {db}.extracted_records_by_victim AS
    SELECT
        archive_sha256,
        splitByChar('/', file_path)[2] AS victim_folder,
        rule_id,
        family,
        file_path,
        fields
    FROM {db}.extracted_records
    WHERE splitByChar('/', file_path)[2] != ''
    """,
    """
    INSERT INTO {db}.extracted_records_by_victim
        (archive_sha256, victim_folder, rule_id, family, file_path, fields)
    SELECT
        archive_sha256,
        splitByChar('/', file_path)[2] AS victim_folder,
        rule_id,
        family,
        file_path,
        fields
    FROM {db}.extracted_records
    WHERE splitByChar('/', file_path)[2] != ''
      AND NOT EXISTS (SELECT 1 FROM {db}.extracted_records_by_victim)
    """,
)


# v1.3.3 per-victim DOMAIN index. One row per (archive_sha256, victim_folder,
# domain, source_kind) with a running count. The whole point of this table
# is detection economics: a future monitored-domain watchlist joins against
# this instead of against extracted_records, so
#
#   WHERE domain LIKE '%acme-corp.com%'
#
# scans a tiny indexed micro-MV and returns victim counts + hit domains in
# sub-ms, no matter how big extracted_records grows. The detail drilldown
# (actual cred row, actual cookie value) falls through to extracted_records
# only when the operator opens the drawer.
#
# ORDER BY puts `domain` first so detection queries get contiguous granule
# scans. The bloom-filter skip index accelerates substring matches on top
# of the sort-order pruning.
#
# Six MVs feed this table from six distinct source rule categories. Each MV
# fires on every INSERT into extracted_records and writes partial counts;
# SimpleAggregateFunction(sum, UInt64) adds them on background merge.
_VICTIM_DOMAINS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS {db}.victim_domains
    (
        archive_sha256 FixedString(64),
        victim_folder  String,
        domain         String,
        source_kind    LowCardinality(String),
        count          SimpleAggregateFunction(sum, UInt64),
        INDEX idx_domain_bf domain TYPE bloom_filter() GRANULARITY 1
    )
    ENGINE = AggregatingMergeTree
    ORDER BY (domain, archive_sha256, victim_folder, source_kind)
    {storage_policy_clause}
    """,
    # cookies -> one domain per cookie row
    """
    CREATE MATERIALIZED VIEW IF NOT EXISTS {db}.victim_domains_cookies_mv
    TO {db}.victim_domains AS
    SELECT
        archive_sha256,
        splitByChar('/', file_path)[2] AS victim_folder,
        lowerUTF8(fields['cookie_domain']) AS domain,
        'cookie' AS source_kind,
        toUInt32(1) AS count
    FROM {db}.extracted_records
    WHERE rule_id = 'cookies_netscape_tsv'
      AND fields['cookie_domain'] != ''
      AND splitByChar('/', file_path)[2] != ''
    """,
    # passwords -> parse host column via CH's domain() function
    """
    CREATE MATERIALIZED VIEW IF NOT EXISTS {db}.victim_domains_creds_mv
    TO {db}.victim_domains AS
    SELECT
        archive_sha256,
        splitByChar('/', file_path)[2] AS victim_folder,
        lowerUTF8(domain(fields['host'])) AS domain,
        'credential' AS source_kind,
        toUInt32(1) AS count
    FROM {db}.extracted_records
    WHERE rule_id LIKE 'passwords_%'
      AND domain(fields['host']) != ''
      AND splitByChar('/', file_path)[2] != ''
    """,
    # browser history visits
    """
    CREATE MATERIALIZED VIEW IF NOT EXISTS {db}.victim_domains_history_mv
    TO {db}.victim_domains AS
    SELECT
        archive_sha256,
        splitByChar('/', file_path)[2] AS victim_folder,
        lowerUTF8(domain(fields['visit_url'])) AS domain,
        'history_visit' AS source_kind,
        toUInt32(1) AS count
    FROM {db}.extracted_records
    WHERE rule_id = 'history_url_title_block'
      AND domain(fields['visit_url']) != ''
      AND splitByChar('/', file_path)[2] != ''
    """,
    # browser downloads
    """
    CREATE MATERIALIZED VIEW IF NOT EXISTS {db}.victim_domains_downloads_mv
    TO {db}.victim_domains AS
    SELECT
        archive_sha256,
        splitByChar('/', file_path)[2] AS victim_folder,
        lowerUTF8(domain(fields['download_url'])) AS domain,
        'download' AS source_kind,
        toUInt32(1) AS count
    FROM {db}.extracted_records
    WHERE rule_id = 'download_history_block'
      AND domain(fields['download_url']) != ''
      AND splitByChar('/', file_path)[2] != ''
    """,
    # browser localStorage origins
    """
    CREATE MATERIALIZED VIEW IF NOT EXISTS {db}.victim_domains_localstorage_mv
    TO {db}.victim_domains AS
    SELECT
        archive_sha256,
        splitByChar('/', file_path)[2] AS victim_folder,
        lowerUTF8(domain(fields['ls_domain'])) AS domain,
        'localstorage' AS source_kind,
        toUInt32(1) AS count
    FROM {db}.extracted_records
    WHERE rule_id IN ('localstorage_block', 'localstorage_jwt_candidates')
      AND fields['ls_domain'] != ''
      AND splitByChar('/', file_path)[2] != ''
    """,
    # webmail provider from the history_webmail_identity rule
    # (splits the extracted email on '@' and takes the right-hand side)
    """
    CREATE MATERIALIZED VIEW IF NOT EXISTS {db}.victim_domains_webmail_mv
    TO {db}.victim_domains AS
    SELECT
        archive_sha256,
        splitByChar('/', file_path)[2] AS victim_folder,
        lowerUTF8(splitByChar('@', fields['webmail_email'])[2]) AS domain,
        'email_webmail' AS source_kind,
        toUInt32(1) AS count
    FROM {db}.extracted_records
    WHERE rule_id = 'history_webmail_identity'
      AND fields['webmail_email'] LIKE '%@%'
      AND splitByChar('/', file_path)[2] != ''
    """,
    # Idempotent backfill. One INSERT per source MV so a partial gate wins
    # per source: if cookies already backfilled but passwords hasn't, we
    # still pick up the gap. NOT EXISTS probe is per source_kind so adding
    # a new source later only backfills the new one.
    """
    INSERT INTO {db}.victim_domains
    SELECT
        archive_sha256,
        splitByChar('/', file_path)[2] AS victim_folder,
        lowerUTF8(fields['cookie_domain']) AS domain,
        'cookie' AS source_kind,
        toUInt32(1) AS count
    FROM {db}.extracted_records
    WHERE rule_id = 'cookies_netscape_tsv'
      AND fields['cookie_domain'] != ''
      AND splitByChar('/', file_path)[2] != ''
      AND NOT EXISTS (SELECT 1 FROM {db}.victim_domains WHERE source_kind = 'cookie')
    """,
    """
    INSERT INTO {db}.victim_domains
    SELECT
        archive_sha256,
        splitByChar('/', file_path)[2],
        lowerUTF8(domain(fields['host'])),
        'credential',
        toUInt32(1)
    FROM {db}.extracted_records
    WHERE rule_id LIKE 'passwords_%'
      AND domain(fields['host']) != ''
      AND splitByChar('/', file_path)[2] != ''
      AND NOT EXISTS (SELECT 1 FROM {db}.victim_domains WHERE source_kind = 'credential')
    """,
    """
    INSERT INTO {db}.victim_domains
    SELECT
        archive_sha256,
        splitByChar('/', file_path)[2],
        lowerUTF8(domain(fields['visit_url'])),
        'history_visit',
        toUInt32(1)
    FROM {db}.extracted_records
    WHERE rule_id = 'history_url_title_block'
      AND domain(fields['visit_url']) != ''
      AND splitByChar('/', file_path)[2] != ''
      AND NOT EXISTS (SELECT 1 FROM {db}.victim_domains WHERE source_kind = 'history_visit')
    """,
    """
    INSERT INTO {db}.victim_domains
    SELECT
        archive_sha256,
        splitByChar('/', file_path)[2],
        lowerUTF8(domain(fields['download_url'])),
        'download',
        toUInt32(1)
    FROM {db}.extracted_records
    WHERE rule_id = 'download_history_block'
      AND domain(fields['download_url']) != ''
      AND splitByChar('/', file_path)[2] != ''
      AND NOT EXISTS (SELECT 1 FROM {db}.victim_domains WHERE source_kind = 'download')
    """,
    """
    INSERT INTO {db}.victim_domains
    SELECT
        archive_sha256,
        splitByChar('/', file_path)[2],
        lowerUTF8(domain(fields['ls_domain'])),
        'localstorage',
        toUInt32(1)
    FROM {db}.extracted_records
    WHERE rule_id IN ('localstorage_block', 'localstorage_jwt_candidates')
      AND fields['ls_domain'] != ''
      AND splitByChar('/', file_path)[2] != ''
      AND NOT EXISTS (SELECT 1 FROM {db}.victim_domains WHERE source_kind = 'localstorage')
    """,
    """
    INSERT INTO {db}.victim_domains
    SELECT
        archive_sha256,
        splitByChar('/', file_path)[2],
        lowerUTF8(splitByChar('@', fields['webmail_email'])[2]),
        'email_webmail',
        toUInt32(1)
    FROM {db}.extracted_records
    WHERE rule_id = 'history_webmail_identity'
      AND fields['webmail_email'] LIKE '%@%'
      AND splitByChar('/', file_path)[2] != ''
      AND NOT EXISTS (SELECT 1 FROM {db}.victim_domains WHERE source_kind = 'email_webmail')
    """,
)


# v1.3.4 monitored-domain watchlist. Operator-curated list of domains /
# domain-suffixes we actively care about: corporate domains the client is
# protecting, known attacker C2 / staging hosts, dropbox URLs, etc.
#
# Schema is deliberately minimal and read-mostly. Writes happen via a small
# admin API (POST /v1/stealer/monitored-domains) and very occasionally in
# bulk from a YAML seed. Reads are the hot path:
#
#   SELECT archive_sha256, victim_folder, groupArrayDistinct(vd.domain) AS hits
#   FROM victim_domains vd
#   INNER JOIN monitored_domains md
#     ON (md.match_type = 'exact'  AND vd.domain = md.domain)
#     OR (md.match_type = 'suffix' AND endsWith(vd.domain, md.domain))
#   GROUP BY archive_sha256, victim_folder
#
# With ~100 monitored domains and millions of victim_domain rows, the join
# is bounded by the small side (monitored_domains) and runs in ms thanks to
# the domain-first ORDER BY on victim_domains.
#
# match_type:
#   'exact'   victim_domain == monitored.domain (case-insensitive)
#   'suffix'  endsWith(victim_domain, monitored.domain). Lets 'acme-corp.com'
#             match 'okta.acme-corp.com', 'vpn.acme-corp.com', etc without
#             the operator having to enumerate every subdomain.
#
# severity: operator-assigned. 'critical' fires the red-dot in the UI and
# can trigger alert webhooks; 'info' is a passive tag.
_MONITORED_DOMAINS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS {db}.monitored_domains
    (
        domain      String,
        match_type  LowCardinality(String) DEFAULT 'suffix',
        severity    LowCardinality(String) DEFAULT 'info',
        tag         LowCardinality(String) DEFAULT '',
        note        String DEFAULT '',
        added_by    String DEFAULT '',
        added_at    DateTime DEFAULT now()
    )
    ENGINE = ReplacingMergeTree(added_at)
    ORDER BY domain
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
        # v1.3.1 one-shot repair: drop + rebuild if the old rule_id-based MV
        # is detected, then let the CREATE IF NOT EXISTS below re-make it
        # with the new family-based body, then the NOT EXISTS backfill fires.
        self._repair_victim_profiles_if_stale(client)
        for stmt in _VICTIM_PROFILES:
            client.command(stmt.format(db=self._db, storage_policy_clause=_storage_policy_clause()))
        # v1.3.3 per-victim domain index (detection engine primitive).
        for stmt in _VICTIM_DOMAINS:
            client.command(stmt.format(db=self._db, storage_policy_clause=_storage_policy_clause()))
        # v1.3.4 monitored-domain watchlist (detection-engine input table).
        for stmt in _MONITORED_DOMAINS:
            client.command(stmt.format(db=self._db))
        # v1.3.1 /stats pre-aggregation rollups (4 MVs + one-shot backfill).
        for stmt in _STATS_ROLLUP:
            client.command(stmt.format(db=self._db, storage_policy_clause=_storage_policy_clause()))
        # v1.3.1 parse-failures acceleration (1 MV + one-shot backfill).
        for stmt in _EXTRACTED_PATHS:
            client.command(stmt.format(db=self._db, storage_policy_clause=_storage_policy_clause()))

    def _repair_victim_profiles_if_stale(self, client: Any) -> None:
        """Drop the pre-1.3.1 victim_profiles table + MV iff the MV body
        still contains the stale rule_id-based count expressions. The
        follow-on CREATE IF NOT EXISTS then rebuilds with the family-based
        body, and the NOT EXISTS backfill repopulates from
        extracted_records. Idempotent: once rebuilt, the sentinel no
        longer matches, so later ensure_schema() calls are no-ops."""
        # self._db is operator-set config, not user input; no injection risk.
        query = (
            "SELECT create_table_query FROM system.tables "  # noqa: S608  # nosec B608
            f"WHERE database = '{self._db}' AND name = 'victim_profiles_mv'"
        )
        rows = client.query(query).result_rows
        if not rows or _VICTIM_PROFILES_STALE_SENTINEL not in (rows[0][0] or ""):
            return
        client.command(f"DROP VIEW IF EXISTS {self._db}.victim_profiles_mv")
        client.command(f"TRUNCATE TABLE IF EXISTS {self._db}.victim_profiles")
        client.command(f"DROP TABLE IF EXISTS {self._db}.victim_profiles")

    def insert_rows(self, rows: Iterable[list[Any]]) -> int:
        batch: list[list[Any]] = list(rows)
        if not batch:
            return 0
        self._connect().insert(
            f"{self._db}.extracted_records",
            batch,
            column_names=_RECORDS_COLUMNS,
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
    "approx_banner_hits",
    "approx_null_pw_hits",
    "sample_head",
    "parse_error",
    "parse_error_detail",
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
    # v1.3.5 drop rows_emitted: never populated by the pipeline (always wrote
    # 0, with a stale "fill later" TODO from v1.2.6 that never happened). The
    # drawer's Files tab now derives the per-file row count from
    # extracted_records via a JOIN in file_tree(), so this column is dead
    # weight. IF EXISTS keeps the ALTER idempotent for fresh installs.
    "ALTER TABLE {db}.file_audit DROP COLUMN IF EXISTS rows_emitted",
    # v1.3.6 per-victim coverage roll-up. Same engine + aggregation shape as
    # file_audit_per_archive but keyed (archive_sha256, victim_folder) so the
    # drawer + parse-failures workbench can show "35 of 48 files parsed for
    # victim AE[...]" without a hand-rolled GROUP BY against file_audit.
    # Excludes files at the archive root (victim_folder = '') because those
    # are channel wrappers (promo, cover, preview), not victim data.
    """
    CREATE TABLE IF NOT EXISTS {db}.file_audit_per_victim
    (
        archive_sha256 FixedString(64),
        victim_folder  String,
        total_files    SimpleAggregateFunction(sum, UInt64),
        parsed_files   SimpleAggregateFunction(sum, UInt64),
        unknown_files  SimpleAggregateFunction(sum, UInt64),
        first_seen_at  SimpleAggregateFunction(min, DateTime),
        last_seen_at   SimpleAggregateFunction(max, DateTime)
    )
    ENGINE = AggregatingMergeTree
    ORDER BY (archive_sha256, victim_folder)
    """,
    """
    CREATE MATERIALIZED VIEW IF NOT EXISTS {db}.file_audit_per_victim_mv
    TO {db}.file_audit_per_victim AS
    SELECT
        archive_sha256,
        victim_folder,
        toUInt64(1) AS total_files,
        toUInt64(extractor_touched) AS parsed_files,
        toUInt64(extractor_touched = 0
                 AND heuristic_kind NOT IN ('empty','binary')) AS unknown_files,
        parsed_at AS first_seen_at,
        parsed_at AS last_seen_at
    FROM {db}.file_audit
    WHERE victim_folder != ''
    """,
    # Idempotent backfill. Same NOT EXISTS gate as the per-archive roll-up.
    # Runs AFTER the MV so historical rows land; new rows come through the MV.
    """
    INSERT INTO {db}.file_audit_per_victim
    SELECT
        archive_sha256,
        victim_folder,
        toUInt64(1) AS total_files,
        toUInt64(extractor_touched) AS parsed_files,
        toUInt64(extractor_touched = 0
                 AND heuristic_kind NOT IN ('empty','binary')) AS unknown_files,
        parsed_at AS first_seen_at,
        parsed_at AS last_seen_at
    FROM {db}.file_audit
    WHERE victim_folder != ''
      AND NOT EXISTS (SELECT 1 FROM {db}.file_audit_per_victim)
    """,
    # v1.3.7 hard-crash tracking. parse_error = short code ('panic', 'timeout',
    # 'decode', ''); parse_error_detail = truncated message. Set per-file by
    # the gotractor daemon via a safeBulkParse recover() wrapper. Operator
    # uses these to tell "gotractor died on this file" apart from the softer
    # "rule matched, zero records emitted" case the workbench shape-groups.
    "ALTER TABLE {db}.file_audit ADD COLUMN IF NOT EXISTS "
    "parse_error LowCardinality(String) DEFAULT ''",
    "ALTER TABLE {db}.file_audit ADD COLUMN IF NOT EXISTS parse_error_detail String DEFAULT ''",
)


# v1.3.8 per-victim stealer-family verdict. One row per (archive_sha256,
# victim_folder). Written by the pipeline + the stealer-reclassify CLI.
# The drawer's detail endpoint reads from this with FINAL so stale
# re-runs collapse; a victim with no verdict row reads as "no verdict
# yet" on the FE. Not an SQL MV because the scorer is Python-side
# (regex + weighted sum + catalog-in-memory); see
# development/STEALER_FAMILY_CLASSIFIER_DESIGN.md.
_VERDICT_CREATE = """
CREATE TABLE IF NOT EXISTS {db}.victim_family_verdict
(
    archive_sha256 FixedString(64),
    victim_folder  String,
    slug           LowCardinality(String),
    confidence     Float32,
    evidence       Array(String),
    runners_up     Array(Tuple(String, Float32)),
    computed_at    DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(computed_at)
ORDER BY (archive_sha256, victim_folder)
{storage_policy_clause}
"""


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
        client.command(
            _VERDICT_CREATE.format(
                db=self._db,
                storage_policy_clause=_storage_policy_clause(),
            )
        )

    def insert_rows(self, rows: Iterable[list[Any]]) -> int:
        batch: list[list[Any]] = list(rows)
        if not batch:
            return 0
        self._connect().insert(f"{self._db}.file_audit", batch, column_names=_FILE_AUDIT_COLUMNS)
        return len(batch)

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None


__all__ = [
    "ClickHouseRecordsSink",
    "FileAuditSink",
    "clickhouse_db",
    "get_async_clickhouse_client",
    "get_clickhouse_client",
]
