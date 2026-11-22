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


# v1.3.1 reindex-idempotent counter semantics. The ClickHouse MV contract is
# "forward the INSERT block, not the post-merge state of the source", so a
# plain count() in an MV over extracted_records (ReplacingMergeTree) double-
# counts when the same row is re-inserted via a reindex. The ReplacingMergeTree
# dedups on its ORDER BY key; if our rollup counter is uniqExact over the
# SAME tuple, it dedups the same way. Correctness becomes a schema property
# instead of a maintenance procedure the operator has to remember.
#
# Identity tuple matches extracted_records' ORDER BY -- archive_sha256,
# rule_id, file_path, cityHash64(toString(fields)).
_IDENTITY_TUPLE_DDL = "(archive_sha256, rule_id, file_path, cityHash64(toString(fields)))"
_IDENTITY_TUPLE_TYPE = "Tuple(FixedString(64), LowCardinality(String), String, UInt64)"

# f-strings are pre-built as module constants so ruff S608 noqa sits on one
# line each; the "variable" they interpolate is a module constant above.
_EXTRACTED_ROWS_PER_FILE_MV = f"""
    CREATE MATERIALIZED VIEW IF NOT EXISTS {{db}}.extracted_rows_per_file_mv
    TO {{db}}.extracted_rows_per_file AS
    SELECT
        archive_sha256,
        file_path,
        uniqHLL12State({_IDENTITY_TUPLE_DDL}) AS cnt
    FROM {{db}}.extracted_records
    GROUP BY archive_sha256, file_path
    """  # noqa: S608  # nosec B608
_EXTRACTED_ROWS_PER_FILE_BACKFILL = f"""
    INSERT INTO {{db}}.extracted_rows_per_file
    SELECT archive_sha256, file_path, uniqHLL12State({_IDENTITY_TUPLE_DDL}) AS cnt
    FROM {{db}}.extracted_records
    WHERE NOT EXISTS (SELECT 1 FROM {{db}}.extracted_rows_per_file)
    GROUP BY archive_sha256, file_path
    """  # noqa: S608  # nosec B608

# victim_profiles MV body + backfill. Shared across both: the SELECT core
# is identical; only the wrapping (INSERT ... vs CREATE MATERIALIZED VIEW)
# differs. Keep them literally separate to match the original structure.
_VICTIM_PROFILES_SELECT_CORE = f"""
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
        uniqHLL12StateIf({_IDENTITY_TUPLE_DDL}, family IN ('browser_passwords','combolist','windows_credentials','json_v2')) AS creds_count,
        uniqHLL12StateIf({_IDENTITY_TUPLE_DDL}, family IN ('cookies','victim_cookies')) AS cookies_count,
        uniqHLL12StateIf({_IDENTITY_TUPLE_DDL}, family = 'victim_autofills') AS autofills_count,
        uniqHLL12StateIf({_IDENTITY_TUPLE_DDL}, family = 'victim_history') AS history_count,
        uniqHLL12StateIf({_IDENTITY_TUPLE_DDL}, family = 'victim_downloads') AS downloads_count,
        uniqHLL12StateIf({_IDENTITY_TUPLE_DDL}, family = 'victim_processes') AS processes_count,
        uniqHLL12StateIf({_IDENTITY_TUPLE_DDL}, family = 'victim_software') AS software_count,
        uniqHLL12StateIf({_IDENTITY_TUPLE_DDL}, family = 'discord_tokens') AS discord_tokens_count,
        uniqHLL12StateIf({_IDENTITY_TUPLE_DDL}, family = 'steam_accounts') AS steam_tokens_count,
        uniqHLL12StateIf({_IDENTITY_TUPLE_DDL}, family = 'google_oauth_tokens') AS google_refresh_count,
        uniqHLL12StateIf({_IDENTITY_TUPLE_DDL}, rule_id = 'localstorage_jwt_candidates') AS localstorage_jwt_count,
        uniqHLL12StateIf({_IDENTITY_TUPLE_DDL}, rule_id LIKE 'wallet_vault_leveldb:%') AS wallet_vaults_count,
        maxIf(toUInt8(1), rule_id = 'software_corporate_marker') AS has_corporate_marker,
        maxIf(toUInt8(1), rule_id = 'history_webmail_identity') AS has_webmail_leak,
        maxIf(toUInt8(1), rule_id LIKE 'wallet_vault_leveldb:%' OR family = 'exodus_wallet') AS has_wallet,
        maxIf(toUInt8(1), family = 'aware_crypter') AS has_crypter_banner,
        maxIf(fields['webmail_email'], rule_id = 'history_webmail_identity') AS webmail_identity,
        maxIf(fields['corporate_marker'], rule_id = 'software_corporate_marker') AS first_corporate_marker,
        maxIf(family, rule_id LIKE 'wallet_vault_leveldb:%') AS first_wallet_family
    FROM {{db}}.extracted_records
"""  # noqa: S608  # nosec B608

_VICTIM_PROFILES_MV = f"""
    CREATE MATERIALIZED VIEW IF NOT EXISTS {{db}}.victim_profiles_mv
    TO {{db}}.victim_profiles AS
    {_VICTIM_PROFILES_SELECT_CORE}
    WHERE splitByChar('/', file_path)[2] != ''
    GROUP BY archive_sha256, victim_folder
    """
_VICTIM_PROFILES_BACKFILL = f"""
    INSERT INTO {{db}}.victim_profiles
    {_VICTIM_PROFILES_SELECT_CORE}
    WHERE splitByChar('/', file_path)[2] != ''
      AND NOT EXISTS (SELECT 1 FROM {{db}}.victim_profiles)
    GROUP BY archive_sha256, victim_folder
    """  # noqa: S608  # nosec B608


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
    f"""
    CREATE TABLE IF NOT EXISTS {{db}}.victim_profiles
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
        creds_count            AggregateFunction(uniqHLL12, {_IDENTITY_TUPLE_TYPE}),
        cookies_count          AggregateFunction(uniqHLL12, {_IDENTITY_TUPLE_TYPE}),
        autofills_count        AggregateFunction(uniqHLL12, {_IDENTITY_TUPLE_TYPE}),
        history_count          AggregateFunction(uniqHLL12, {_IDENTITY_TUPLE_TYPE}),
        downloads_count        AggregateFunction(uniqHLL12, {_IDENTITY_TUPLE_TYPE}),
        processes_count        AggregateFunction(uniqHLL12, {_IDENTITY_TUPLE_TYPE}),
        software_count         AggregateFunction(uniqHLL12, {_IDENTITY_TUPLE_TYPE}),
        discord_tokens_count   AggregateFunction(uniqHLL12, {_IDENTITY_TUPLE_TYPE}),
        steam_tokens_count     AggregateFunction(uniqHLL12, {_IDENTITY_TUPLE_TYPE}),
        google_refresh_count   AggregateFunction(uniqHLL12, {_IDENTITY_TUPLE_TYPE}),
        localstorage_jwt_count AggregateFunction(uniqHLL12, {_IDENTITY_TUPLE_TYPE}),
        wallet_vaults_count    AggregateFunction(uniqHLL12, {_IDENTITY_TUPLE_TYPE}),
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
    {{storage_policy_clause}}
    """,
    # v1.3.1: switched the *_count columns from SAF(sum, UInt64) +
    # countIf(...) in the MV body to AggregateFunction(uniqHLL12, identity_tuple)
    # + uniqHLL12StateIf(identity_tuple, predicate). The identity tuple
    # matches extracted_records' ReplacingMergeTree ORDER BY so a reindex
    # re-inserting the same row contributes the same tuple, and the counter
    # dedups. Correctness is a schema property, not an operator procedure.
    # The "max" fields stay SAF(max) since the gotcha is specific to count.
    _VICTIM_PROFILES_MV,
    # Idempotent backfill with NOT EXISTS gate. First-run on an existing
    # extracted_records populates all historical rows; subsequent calls on
    # each pipeline run are no-ops. v1.3.1: also fires after the one-shot
    # repair (see _repair_victim_profiles_if_stale) rebuilds the table.
    _VICTIM_PROFILES_BACKFILL,
)


# v1.3.1 one-shot repair sentinel. The pre-1.3.1 MV body counted creds by
# `rule_id LIKE 'passwords_%'` (never matches: real rule_ids are
# passwords_block_title, combolist_*, credentials_windows, etc.) and
# cookies by `rule_id = 'cookies_netscape_tsv'` (misses the bulk
# netscape_cookies hits). Prod was showing 0 creds / 0 cookies on
# 3.6M-row extracted_records. The new MV keys off `family` (stable,
# catalog-defined). This string is the sentinel we grep in
# system.tables.create_table_query to decide whether to force-rebuild.
#
# v1.3.12.1 bump: the v1.3.1-to-v1.3.12.0 MV body uses uniqExactStateIf,
# which grew unbounded with cardinality and triggered code 241 merges on
# prod (victim_profiles max merge peak 3.47 GiB). The sentinel now
# catches `uniqHLL12StateIf(` so an upgrade from v1.3.12.0 force-
# rebuilds the MV with the uniqHLL12StateIf body. Pre-v1.3.1 boxes
# (sentinel: `countIf(`) are stale by a different path; they need a
# manual repair or a fresh install -- EYENET has none in the wild.
_VICTIM_PROFILES_STALE_SENTINEL = "uniqHLL12StateIf("

# v1.3.4.3 flat-counts sibling. victim_profiles holds the exact, reindex-
# idempotent uniqExactState columns; victim_counts holds the finalized
# UInt64 scalars, refreshed every 5 minutes by a REFRESHABLE MV. The API
# list/detail paths read from victim_counts FINAL (sub-100ms on 20k rows),
# so an operator filter like has_wallet=1 no longer pays the 7s state
# materialization per request.
_VICTIM_COUNTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS {db}.victim_counts
    (
        archive_sha256         FixedString(64),
        victim_folder          String,
        source                 LowCardinality(String),
        country                LowCardinality(String),
        egress_ip              String,
        user_name              String,
        computer_name          String,
        os_version             String,
        traffic_affid          LowCardinality(String),
        build_version          LowCardinality(String),
        payload_md5            String,
        work_dir               String,
        creds_count            UInt64,
        cookies_count          UInt64,
        autofills_count        UInt64,
        history_count          UInt64,
        downloads_count        UInt64,
        processes_count        UInt64,
        software_count         UInt64,
        discord_tokens_count   UInt64,
        steam_tokens_count     UInt64,
        google_refresh_count   UInt64,
        localstorage_jwt_count UInt64,
        wallet_vaults_count    UInt64,
        has_corporate_marker   UInt8,
        has_webmail_leak       UInt8,
        has_wallet             UInt8,
        has_crypter_banner     UInt8,
        webmail_identity       String,
        first_corporate_marker String,
        first_wallet_family    LowCardinality(String),
        refreshed_at           DateTime DEFAULT now(),
        INDEX idx_country country TYPE set(0) GRANULARITY 1,
        INDEX idx_affid traffic_affid TYPE set(0) GRANULARITY 1,
        INDEX idx_has_wallet has_wallet TYPE set(0) GRANULARITY 1,
        INDEX idx_has_corporate has_corporate_marker TYPE set(0) GRANULARITY 1
    )
    ENGINE = ReplacingMergeTree(refreshed_at)
    ORDER BY (archive_sha256, victim_folder)
    {storage_policy_clause}
    """,
    """
    CREATE MATERIALIZED VIEW IF NOT EXISTS {db}.victim_counts_refresh
    REFRESH EVERY 5 MINUTE
    TO {db}.victim_counts
    AS SELECT
        archive_sha256,
        victim_folder,
        max(source) AS source,
        max(country) AS country,
        max(egress_ip) AS egress_ip,
        max(user_name) AS user_name,
        max(computer_name) AS computer_name,
        max(os_version) AS os_version,
        max(traffic_affid) AS traffic_affid,
        max(build_version) AS build_version,
        max(payload_md5) AS payload_md5,
        max(work_dir) AS work_dir,
        uniqHLL12Merge(creds_count) AS creds_count,
        uniqHLL12Merge(cookies_count) AS cookies_count,
        uniqHLL12Merge(autofills_count) AS autofills_count,
        uniqHLL12Merge(history_count) AS history_count,
        uniqHLL12Merge(downloads_count) AS downloads_count,
        uniqHLL12Merge(processes_count) AS processes_count,
        uniqHLL12Merge(software_count) AS software_count,
        uniqHLL12Merge(discord_tokens_count) AS discord_tokens_count,
        uniqHLL12Merge(steam_tokens_count) AS steam_tokens_count,
        uniqHLL12Merge(google_refresh_count) AS google_refresh_count,
        uniqHLL12Merge(localstorage_jwt_count) AS localstorage_jwt_count,
        uniqHLL12Merge(wallet_vaults_count) AS wallet_vaults_count,
        max(has_corporate_marker) AS has_corporate_marker,
        max(has_webmail_leak) AS has_webmail_leak,
        max(has_wallet) AS has_wallet,
        max(has_crypter_banner) AS has_crypter_banner,
        max(webmail_identity) AS webmail_identity,
        max(first_corporate_marker) AS first_corporate_marker,
        max(first_wallet_family) AS first_wallet_family,
        now() AS refreshed_at
    FROM {db}.victim_profiles
    GROUP BY archive_sha256, victim_folder
    SETTINGS optimize_aggregation_in_order = 1, max_bytes_before_external_group_by = 200000000, max_memory_usage = 5000000000
    """,
)

# v1.3.5 flat-counts sibling for extracted_rows_per_file. Same pattern as
# victim_counts: the base AggregatingMergeTree keeps the aggregate state
# column for reindex-idempotent dedup; a ReplacingMergeTree sibling
# holds the finalized plain UInt64 scalars, refreshed every 5 minutes by a
# REFRESHABLE MV. file_tree + _coverage read from here instead of paying
# the base table's aggregate-state deserialization on every click.
# v1.3.12.1 swapped the base from uniqExact -> uniqHLL12 to cap per-bucket
# state at ~2.5 KiB (counts are a dashboard stat, ~2.5% error is fine).
_EXTRACTED_ROWS_PER_FILE_COUNTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS {db}.extracted_rows_per_file_counts
    (
        archive_sha256 FixedString(64),
        file_path      String,
        n              UInt64,
        refreshed_at   DateTime DEFAULT now()
    )
    ENGINE = ReplacingMergeTree(refreshed_at)
    ORDER BY (archive_sha256, file_path)
    {storage_policy_clause}
    """,
    """
    CREATE MATERIALIZED VIEW IF NOT EXISTS {db}.extracted_rows_per_file_counts_refresh
    REFRESH EVERY 5 MINUTE
    TO {db}.extracted_rows_per_file_counts
    AS SELECT
        archive_sha256,
        file_path,
        uniqHLL12Merge(cnt) AS n,
        now() AS refreshed_at
    FROM {db}.extracted_rows_per_file
    GROUP BY archive_sha256, file_path
    SETTINGS optimize_aggregation_in_order = 1, max_bytes_before_external_group_by = 200000000, max_memory_usage = 5000000000
    """,
)

# v1.3.6 Domain View: materialised host columns on extracted_records so the
# WHERE host_registrable = 'google.com' predicate can prune via a bloom-filter
# skip index. Without these the operator had to evaluate
# ``lower(coalesce(nullIf(domain(fields['url']), ...)))`` on every row, which
# is a 54s full-table scan on 100M rows. Measured on prod after materialisation:
# 54s -> 220ms (~250x) and empirical bloom FP rate 0.16% (6x tighter than the
# configured 0.01 target). All three ALTERs are idempotent via IF NOT EXISTS
# so bootstrap on an existing deployment is a no-op after the first run.
# v1.3.10 extended coverage: original expression only matched browser_passwords
# (url + host). Cookies store the host as fields['cookie_domain'] with a leading
# dot (.criteo.com), history uses fields['visit_url'], and both were rendering
# host_canon = '' -- the /by-domain cookies tab returned zero rows for every
# domain because the bloom index pruned every granule. The coalesce chain now
# covers all three families; trim(LEADING '.') strips the cookie-domain prefix
# so google.com matches both passwords and cookies through one predicate.
_HOST_CANON_EXPR = (
    "lower(coalesce("
    "nullIf(domain(fields['url']), ''),"
    "nullIf(domain(fields['visit_url']), ''),"
    "nullIf(domain(fields['host']), ''),"
    "nullIf(fields['host'], ''),"
    "nullIf(trim(LEADING '.' FROM fields['cookie_domain']), ''),"
    "''))"
)

_EXTRACTED_RECORDS_HOST_COLS: tuple[str, ...] = (
    f"""
    ALTER TABLE {{db}}.extracted_records
      ADD COLUMN IF NOT EXISTS host_canon String MATERIALIZED
        {_HOST_CANON_EXPR},
      ADD COLUMN IF NOT EXISTS host_registrable String MATERIALIZED
        cutToFirstSignificantSubdomain({_HOST_CANON_EXPR}),
      ADD INDEX IF NOT EXISTS idx_host_registrable host_registrable
        TYPE bloom_filter(0.01) GRANULARITY 4
    """,
    # For a deployment that already has the columns from v1.3.6, bring them
    # up to the extended expression. CH silently no-ops MODIFY COLUMN when the
    # new expression equals the stored one, so this is safe to run every boot.
    f"""
    ALTER TABLE {{db}}.extracted_records
      MODIFY COLUMN host_canon String MATERIALIZED {_HOST_CANON_EXPR},
      MODIFY COLUMN host_registrable String MATERIALIZED
        cutToFirstSignificantSubdomain({_HOST_CANON_EXPR})
    """,
)

# v1.3.6 by-domain flat-counts sibling for /v1/stealer/by-domain/{domain}/summary.
# Same ReplacingMergeTree + REFRESHABLE MV pattern as victim_counts and
# extracted_rows_per_file_counts. Hero card reads one row from here with FINAL
# (cheap, 45ms warm on prod). Deep tabs (credentials / cookies / autofills /
# history / subdomains) hit extracted_records directly, scoped by
# host_registrable + bloom filter. Dedup grains match the deep-tab queries
# (url+login+password for creds, url+name for cookies, etc.) so hero numbers
# agree with per-tab pagination totals.
_BY_DOMAIN_COUNTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS {db}.by_domain_counts
    (
        host_registrable       String,
        victim_count           UInt64,
        archive_count          UInt64,
        first_seen_at          DateTime,
        last_seen_at           DateTime,
        credential_count       UInt64,
        live_cookie_count      UInt64,
        all_cookie_count       UInt64,
        autofill_count         UInt64,
        history_count          UInt64,
        localstorage_jwt_count UInt64,
        indicator_hit_count    UInt64,
        refreshed_at           DateTime DEFAULT now()
    )
    ENGINE = ReplacingMergeTree(refreshed_at)
    ORDER BY host_registrable
    {storage_policy_clause}
    """,
    """
    CREATE MATERIALIZED VIEW IF NOT EXISTS {db}.by_domain_counts_refresh
    REFRESH EVERY 5 MINUTE
    TO {db}.by_domain_counts
    AS SELECT
        host_registrable,
        uniqHLL12If((archive_sha256, victim_folder),
          family IN ('browser_passwords','windows_credentials',
                     'firefox_logins','combolist')) AS victim_count,
        uniqHLL12If(archive_sha256,
          family IN ('browser_passwords','windows_credentials',
                     'firefox_logins','combolist')
          OR family IN ('cookies','victim_cookies')) AS archive_count,
        min(ingested_at) AS first_seen_at,
        max(ingested_at) AS last_seen_at,
        uniqHLL12If((fields['url'], fields['user'], fields['password']),
          family IN ('browser_passwords','windows_credentials',
                     'firefox_logins','combolist')) AS credential_count,
        -- v1.3.10: cookies store identity as (cookie_domain, cookie_name) and
        -- expiry as an epoch in cookie_expires_epoch / expires_epoch. The old
        -- (fields['url'], fields['name']) tuple was empty on every cookie row
        -- so LIVE/ALL both rendered 0 (or 1 when an accidental row had both).
        uniqHLL12If((trim(LEADING '.' FROM fields['cookie_domain']),
                         coalesce(nullIf(fields['cookie_name'], ''), fields['name'])),
          family IN ('cookies','victim_cookies')
          AND fromUnixTimestamp(toUInt32OrZero(coalesce(
                nullIf(fields['cookie_expires_epoch'], ''),
                nullIf(fields['expires_epoch'], ''), '0'))) > now()
          ) AS live_cookie_count,
        uniqHLL12If((trim(LEADING '.' FROM fields['cookie_domain']),
                         coalesce(nullIf(fields['cookie_name'], ''), fields['name'])),
          family IN ('cookies','victim_cookies')) AS all_cookie_count,
        -- v1.3.10: autofills always resolve host_registrable='' (Chromium
        -- Web Data has no URL per row), so this per-host bucket is always
        -- 0. The Autofills tab uses a victim-pool join to display real
        -- rows; a correct hero counter needs a dedicated live query on the
        -- summary endpoint (see RENAME_EXTRACTED_INDICATORS_SCOPE.md).
        -- Hard-coded 0 here keeps the MV honest; FE renders as a dash.
        0 AS autofill_count,
        -- v1.3.10: history rule emits fields['visit_url'], not ['url'].
        -- The old expression counted 0 for every domain. visit_downloads
        -- still uses 'url' so we coalesce both.
        uniqHLL12If(coalesce(nullIf(fields['visit_url'], ''), fields['url']),
          family IN ('victim_history','victim_downloads')) AS history_count,
        uniqHLL12If(fields['value'],
          rule_id = 'localstorage_jwt_candidates') AS localstorage_jwt_count,
        -- v1.3.9 bug: this used to be uniqHLL12If(rule_id, rule_id != '')
        -- which counted every extraction rule as an "indicator hit" and
        -- surfaced a flashy "N INDICATOR HITS" badge on every domain with
        -- data. The real indicator concept is a join against the operator-
        -- authored monitored_domains watchlist (see query.py
        -- _monitored_domain_hits). Hard-coded to 0 until that join is wired
        -- into the summary MV; the Indicators tab endpoint still returns
        -- real rule-id counts for the tab contents.
        0 AS indicator_hit_count,
        now() AS refreshed_at
    FROM {db}.extracted_records
    WHERE host_registrable != ''
    GROUP BY host_registrable
    SETTINGS optimize_aggregation_in_order = 1,
             max_bytes_before_external_group_by = 200000000, max_memory_usage = 5000000000
    """,
)

# v1.3.8 per-domain per-victim sibling. Backs the Domain View Victims tab
# (and future by-domain Samples/Antiviruses tabs) with sub-20ms warm lookups
# instead of scanning extracted_records on every page flip. Keyed on
# (host_registrable, archive_sha256, victim_folder). Measured on prod:
# 574ms single-stage -> 12-16ms sibling warm, 679ms cold on google.com.
# Row count ~730k (host x victim product filtered to actual matches).
# Same semantic as the single-stage query: per-victim DOMAIN-SCOPED unique
# cred/cookie counts, so operators see "this victim leaked N test.com creds"
# and sum(items.cred_count) >= by_domain_counts.credential_count (the latter
# dedupes credentials ACROSS victims, which is a legitimately different
# question).
_BY_DOMAIN_VICTIM_COUNTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS {db}.by_domain_victim_counts
    (
        host_registrable  String,
        archive_sha256    FixedString(64),
        victim_folder     String,
        country           String,
        build_version     String,
        loader_md5        String,
        cred_count        UInt64,
        cookie_count      UInt64,
        first_seen_at     DateTime,
        last_seen_at      DateTime,
        refreshed_at      DateTime DEFAULT now()
    )
    ENGINE = ReplacingMergeTree(refreshed_at)
    ORDER BY (host_registrable, archive_sha256, victim_folder)
    {storage_policy_clause}
    """,
    """
    CREATE MATERIALIZED VIEW IF NOT EXISTS {db}.by_domain_victim_counts_refresh
    REFRESH EVERY 5 MINUTE
    TO {db}.by_domain_victim_counts
    AS SELECT
        er.host_registrable AS host_registrable,
        er.archive_sha256   AS archive_sha256,
        er.victim_folder    AS victim_folder,
        coalesce(any(vc.country), '')       AS country,
        coalesce(any(vc.build_version), '') AS build_version,
        coalesce(any(vc.payload_md5), '')   AS loader_md5,
        uniqHLL12If(
          (er.fields['url'], er.fields['user'], er.fields['password']),
          er.family IN ('browser_passwords','windows_credentials',
                        'firefox_logins','combolist')) AS cred_count,
        uniqHLL12If(
          (er.fields['url'], er.fields['name']),
          er.family IN ('cookies','victim_cookies')) AS cookie_count,
        min(er.ingested_at) AS first_seen_at,
        max(er.ingested_at) AS last_seen_at,
        now() AS refreshed_at
    FROM {db}.extracted_records AS er
    LEFT JOIN {db}.victim_counts AS vc FINAL
           USING (archive_sha256, victim_folder)
    WHERE er.host_registrable != ''
    GROUP BY er.host_registrable, er.archive_sha256, er.victim_folder
    SETTINGS optimize_aggregation_in_order = 1,
             max_bytes_before_external_group_by = 200000000, max_memory_usage = 5000000000
    """,
)

# v1.3.1 stats-rollup and extracted_rows_per_file switchover.
# v1.3.12.1 bump: uniqExact -> uniqHLL12 (~2.5 KB fixed state, ~2.5% error).
# v1.3.12.2 bump: stats_rollup_totals_mv's unique_creds tuple was reading
# `fields['login']`, which the DSL NEVER emits -- every creds rule emits
# `fields['user']` instead. The sentinel now catches `fields['login']`
# so an upgrade from v1.3.12.0 or v1.3.12.1 force-rebuilds that one MV
# with the correct field name. The other four rollup MVs do not
# reference the login field at all, so the same sentinel is a no-op
# for them (their bodies still match the current uniqHLL12 shape).
_STATS_ROLLUP_STALE_SENTINEL = "fields['login']"
_EXTRACTED_ROWS_PER_FILE_STALE_SENTINEL = "uniqHLL12State("


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
        uniqHLL12State({_IDENTITY_TUPLE_DDL}) AS total_creds,
        uniqHLL12State(({_HOST_EXPR_DDL}, fields['user'], fields['password'])) AS unique_creds,
        uniqHLL12State({_HOST_EXPR_DDL}) AS distinct_hosts
    FROM {{db}}.extracted_records
    WHERE {_STATS_WHERE}
    GROUP BY bucket
    """  # noqa: S608  # nosec B608
_STATS_ROLLUP_SCHEME_MV = f"""
    CREATE MATERIALIZED VIEW IF NOT EXISTS {{db}}.stats_rollup_scheme_mv
    TO {{db}}.stats_rollup_scheme AS
    SELECT
        {_SCHEME_EXPR_DDL} AS scheme,
        uniqHLL12State({_IDENTITY_TUPLE_DDL}) AS cnt
    FROM {{db}}.extracted_records
    WHERE {_STATS_WHERE} AND notEmpty({_SCHEME_EXPR_DDL})
    GROUP BY scheme
    """  # noqa: S608  # nosec B608
_STATS_ROLLUP_TLD_MV = f"""
    CREATE MATERIALIZED VIEW IF NOT EXISTS {{db}}.stats_rollup_tld_mv
    TO {{db}}.stats_rollup_tld AS
    SELECT
        {_TLD_EXPR_DDL} AS tld,
        uniqHLL12State({_IDENTITY_TUPLE_DDL}) AS cnt
    FROM {{db}}.extracted_records
    WHERE {_STATS_WHERE} AND notEmpty({_TLD_EXPR_DDL})
    GROUP BY tld
    """  # noqa: S608  # nosec B608
_STATS_ROLLUP_HOST_MV = f"""
    CREATE MATERIALIZED VIEW IF NOT EXISTS {{db}}.stats_rollup_host_mv
    TO {{db}}.stats_rollup_host AS
    SELECT
        {_HOST_EXPR_DDL} AS host,
        uniqHLL12State({_IDENTITY_TUPLE_DDL}) AS cnt
    FROM {{db}}.extracted_records
    WHERE {_STATS_WHERE} AND notEmpty({_HOST_EXPR_DDL})
    GROUP BY host
    """  # noqa: S608  # nosec B608
_STATS_ROLLUP_TOTALS_BACKFILL = f"""
    INSERT INTO {{db}}.stats_rollup_totals
    SELECT
        'all' AS bucket,
        uniqHLL12State({_IDENTITY_TUPLE_DDL}) AS total_creds,
        uniqHLL12State(({_HOST_EXPR_DDL}, fields['user'], fields['password'])) AS unique_creds,
        uniqHLL12State({_HOST_EXPR_DDL}) AS distinct_hosts
    FROM {{db}}.extracted_records
    WHERE {_STATS_WHERE}
      AND NOT EXISTS (SELECT 1 FROM {{db}}.stats_rollup_totals)
    GROUP BY bucket
    """  # noqa: S608  # nosec B608
_STATS_ROLLUP_SCHEME_BACKFILL = f"""
    INSERT INTO {{db}}.stats_rollup_scheme
    SELECT {_SCHEME_EXPR_DDL} AS scheme, uniqHLL12State({_IDENTITY_TUPLE_DDL}) AS cnt
    FROM {{db}}.extracted_records
    WHERE {_STATS_WHERE} AND notEmpty({_SCHEME_EXPR_DDL})
      AND NOT EXISTS (SELECT 1 FROM {{db}}.stats_rollup_scheme)
    GROUP BY scheme
    """  # noqa: S608  # nosec B608
_STATS_ROLLUP_TLD_BACKFILL = f"""
    INSERT INTO {{db}}.stats_rollup_tld
    SELECT {_TLD_EXPR_DDL} AS tld, uniqHLL12State({_IDENTITY_TUPLE_DDL}) AS cnt
    FROM {{db}}.extracted_records
    WHERE {_STATS_WHERE} AND notEmpty({_TLD_EXPR_DDL})
      AND NOT EXISTS (SELECT 1 FROM {{db}}.stats_rollup_tld)
    GROUP BY tld
    """  # noqa: S608  # nosec B608
_STATS_ROLLUP_HOST_BACKFILL = f"""
    INSERT INTO {{db}}.stats_rollup_host
    SELECT {_HOST_EXPR_DDL} AS host, uniqHLL12State({_IDENTITY_TUPLE_DDL}) AS cnt
    FROM {{db}}.extracted_records
    WHERE {_STATS_WHERE} AND notEmpty({_HOST_EXPR_DDL})
      AND NOT EXISTS (SELECT 1 FROM {{db}}.stats_rollup_host)
    GROUP BY host
    """  # noqa: S608  # nosec B608

_STATS_ROLLUP: tuple[str, ...] = (
    f"""
    CREATE TABLE IF NOT EXISTS {{db}}.stats_rollup_totals
    (
        bucket         LowCardinality(String),
        total_creds    AggregateFunction(uniqHLL12, {_IDENTITY_TUPLE_TYPE}),
        unique_creds   AggregateFunction(uniqHLL12, Tuple(String, String, String)),
        distinct_hosts AggregateFunction(uniqHLL12, String)
    )
    ENGINE = AggregatingMergeTree
    ORDER BY bucket
    {{storage_policy_clause}}
    """,
    _STATS_ROLLUP_TOTALS_MV,
    f"""
    CREATE TABLE IF NOT EXISTS {{db}}.stats_rollup_scheme
    (
        scheme LowCardinality(String),
        cnt    AggregateFunction(uniqHLL12, {_IDENTITY_TUPLE_TYPE})
    )
    ENGINE = AggregatingMergeTree
    ORDER BY scheme
    {{storage_policy_clause}}
    """,
    _STATS_ROLLUP_SCHEME_MV,
    f"""
    CREATE TABLE IF NOT EXISTS {{db}}.stats_rollup_tld
    (
        tld LowCardinality(String),
        cnt AggregateFunction(uniqHLL12, {_IDENTITY_TUPLE_TYPE})
    )
    ENGINE = AggregatingMergeTree
    ORDER BY tld
    {{storage_policy_clause}}
    """,
    _STATS_ROLLUP_TLD_MV,
    f"""
    CREATE TABLE IF NOT EXISTS {{db}}.stats_rollup_host
    (
        host String,
        cnt  AggregateFunction(uniqHLL12, {_IDENTITY_TUPLE_TYPE})
    )
    ENGINE = AggregatingMergeTree
    ORDER BY host
    {{storage_policy_clause}}
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
    f"""
    CREATE TABLE IF NOT EXISTS {{db}}.extracted_rows_per_file
    (
        archive_sha256 FixedString(64),
        file_path      String,
        cnt            AggregateFunction(uniqHLL12, {_IDENTITY_TUPLE_TYPE})
    )
    ENGINE = AggregatingMergeTree
    ORDER BY (archive_sha256, file_path)
    {{storage_policy_clause}}
    """,
    _EXTRACTED_ROWS_PER_FILE_MV,
    _EXTRACTED_ROWS_PER_FILE_BACKFILL,
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


def _repair_mv_if_stale(
    client: Any,
    *,
    db: str,
    mv_name: str,
    target_name: str,
    sentinel: str,
) -> None:
    """Drop {mv_name} + {target_name} iff the stored MV body contains
    {sentinel}. The follow-on CREATE IF NOT EXISTS then rebuilds both
    with the new body and the NOT EXISTS backfill repopulates.

    Module-level so both ClickHouseRecordsSink and FileAuditSink can
    use it without inheritance. `db` is operator-set config, not user
    input; no injection risk.
    """
    query = (
        "SELECT create_table_query FROM system.tables "  # noqa: S608  # nosec B608
        f"WHERE database = '{db}' AND name = '{mv_name}'"
    )
    rows = client.query(query).result_rows
    if not rows or sentinel not in (rows[0][0] or ""):
        return
    client.command(f"DROP VIEW IF EXISTS {db}.{mv_name}")
    client.command(f"TRUNCATE TABLE IF EXISTS {db}.{target_name}")
    client.command(f"DROP TABLE IF EXISTS {db}.{target_name}")


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
        # v1.3.12.1 repair victim_counts_refresh if it still uses
        # uniqExactMerge over columns that are now uniqHLL12 aggregates.
        # Drops the refresh MV + target; the CREATE IF NOT EXISTS below
        # rebuilds both, and the next 5-min refresh repopulates
        # victim_counts from the rebuilt victim_profiles.
        self._repair_mv_if_stale(
            client,
            mv_name="victim_counts_refresh",
            target_name="victim_counts",
            sentinel="uniqHLL12Merge(",
        )
        # v1.3.4.3 flat-counts sibling + refreshable MV. The experimental
        # flag has to be enabled per-command because refreshable MVs are
        # still gated in 24.8. Prod also carries it in the eyenet profile
        # override so SYSTEM REFRESH VIEW works outside this session.
        for stmt in _VICTIM_COUNTS:
            client.command(
                stmt.format(db=self._db, storage_policy_clause=_storage_policy_clause()),
                settings={"allow_experimental_refreshable_materialized_view": 1},
            )
        # v1.3.3 per-victim domain index (detection engine primitive).
        for stmt in _VICTIM_DOMAINS:
            client.command(stmt.format(db=self._db, storage_policy_clause=_storage_policy_clause()))
        # v1.3.4 monitored-domain watchlist (detection-engine input table).
        for stmt in _MONITORED_DOMAINS:
            client.command(stmt.format(db=self._db))
        # v1.3.1 one-shot repair for the rollups whose counter type changed
        # from SAF(sum, UInt64) to AggregateFunction(uniqHLL12, identity_tuple).
        # The sentinel is the pre-1.3.1 MV body's `toUInt64(count())`; if present
        # the MV + target are dropped and the CREATE IF NOT EXISTS below
        # rebuilds them with the new body, then the NOT EXISTS backfill fires.
        for mv in (
            "stats_rollup_totals_mv",
            "stats_rollup_scheme_mv",
            "stats_rollup_tld_mv",
            "stats_rollup_host_mv",
            "extracted_rows_per_file_mv",
        ):
            self._repair_mv_if_stale(
                client,
                mv_name=mv,
                target_name=mv.removesuffix("_mv"),
                sentinel=_STATS_ROLLUP_STALE_SENTINEL,
            )
        # v1.3.1 /stats pre-aggregation rollups (4 MVs + one-shot backfill).
        for stmt in _STATS_ROLLUP:
            client.command(stmt.format(db=self._db, storage_policy_clause=_storage_policy_clause()))
        # v1.3.1 parse-failures acceleration (1 MV + one-shot backfill).
        for stmt in _EXTRACTED_PATHS:
            client.command(stmt.format(db=self._db, storage_policy_clause=_storage_policy_clause()))
        # v1.3.12.1 repair extracted_rows_per_file_counts_refresh if it still
        # uses uniqExactMerge over a column that is now uniqHLL12.
        self._repair_mv_if_stale(
            client,
            mv_name="extracted_rows_per_file_counts_refresh",
            target_name="extracted_rows_per_file_counts",
            sentinel="uniqHLL12Merge(",
        )
        # v1.3.5 flat-counts sibling + refreshable MV for extracted_rows_per_file.
        # Must run AFTER extracted_rows_per_file itself is created (above).
        for stmt in _EXTRACTED_ROWS_PER_FILE_COUNTS:
            client.command(
                stmt.format(db=self._db, storage_policy_clause=_storage_policy_clause()),
                settings={"allow_experimental_refreshable_materialized_view": 1},
            )
        # v1.3.6 Domain View: materialised host columns + bloom index on
        # extracted_records, plus the by_domain_counts sibling. ALTERs are
        # idempotent; MATERIALIZE COLUMN on an existing populated corpus is
        # NOT run here (slow, operator decision) -- CH computes the
        # expression on-the-fly until MATERIALIZE is kicked off manually.
        for stmt in _EXTRACTED_RECORDS_HOST_COLS:
            client.command(stmt.format(db=self._db))
        # v1.3.12.2 repair by_domain_counts_refresh if it still uses
        # countDistinctIf (unbounded exact state, OOMed at 7.5 GiB on
        # prod against 157M rows). Drop + rebuild with uniqHLL12If body.
        self._repair_mv_if_stale(
            client,
            mv_name="by_domain_counts_refresh",
            target_name="by_domain_counts",
            sentinel="countDistinctIf(",
        )
        for stmt in _BY_DOMAIN_COUNTS:
            client.command(
                stmt.format(db=self._db, storage_policy_clause=_storage_policy_clause()),
                settings={"allow_experimental_refreshable_materialized_view": 1},
            )
        # v1.3.8 per-domain per-victim sibling (Domain View Victims tab).
        # Depends on the _EXTRACTED_RECORDS_HOST_COLS block above for the
        # host_registrable column; MV groups on it.
        # v1.3.12.2 repair: same countDistinctIf -> uniqHLL12If swap.
        self._repair_mv_if_stale(
            client,
            mv_name="by_domain_victim_counts_refresh",
            target_name="by_domain_victim_counts",
            sentinel="countDistinctIf(",
        )
        for stmt in _BY_DOMAIN_VICTIM_COUNTS:
            client.command(
                stmt.format(db=self._db, storage_policy_clause=_storage_policy_clause()),
                settings={"allow_experimental_refreshable_materialized_view": 1},
            )

    def _repair_victim_profiles_if_stale(self, client: Any) -> None:
        """Drop the pre-1.3.1 victim_profiles table + MV iff the MV body
        still contains the stale countIf expressions. Idempotent."""
        self._repair_mv_if_stale(
            client,
            mv_name="victim_profiles_mv",
            target_name="victim_profiles",
            sentinel=_VICTIM_PROFILES_STALE_SENTINEL,
        )

    def _repair_mv_if_stale(
        self,
        client: Any,
        *,
        mv_name: str,
        target_name: str,
        sentinel: str,
    ) -> None:
        """Instance wrapper -- delegates to the module-level helper so
        FileAuditSink can call the same code without inheriting."""
        _repair_mv_if_stale(
            client, db=self._db, mv_name=mv_name, target_name=target_name, sentinel=sentinel,
        )

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
        archive_count_state  AggregateFunction(uniqHLL12, FixedString(64)),
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
        uniqHLL12State(archive_sha256) AS archive_count_state,
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
        uniqHLL12State(archive_sha256) AS archive_count_state,
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
        # v1.3.12.2 repair file_audit_per_unknown_file if it still uses
        # AggregateFunction(uniqExact, ...) + uniqExactState on the
        # archive_count_state column. Swap to uniqHLL12 across the board
        # for consistency with the rest of the corpus. Dropping the
        # target discards the archive-count aggregate state; the backfill
        # INSERT (NOT EXISTS gated in the _FILE_AUDIT_V127 block)
        # repopulates from the live file_audit table.
        _repair_mv_if_stale(
            client,
            db=self._db,
            mv_name="file_audit_per_unknown_file_mv",
            target_name="file_audit_per_unknown_file",
            sentinel="uniqExactState(",
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
