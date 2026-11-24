# SPDX-License-Identifier: AGPL-3.0-or-later
"""ClickHouse sinks for the stealer corpus.

Thin wrapper over clickhouse-connect (HTTP). Owns two write paths:

- ``ClickHouseRecordsSink`` + ``_records_create``: gotractor's two plane
  landing tables ``stealer.extracted_records_credlist`` (firehose) and
  ``stealer.extracted_records_victim`` (dedup key is a hash of the fields
  Map). The primary corpus. See development/CH_PLANE_SEPARATION_SCOPE.md.
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

from eyenet.telemetry.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Iterable

    from clickhouse_connect.driver.client import Client

_log = get_logger()

_CREATE_DB = "CREATE DATABASE IF NOT EXISTS {db}"

# The ulpextract-era <db>.creds DDL + its _COLUMNS / _ALTER_TABLE chain
# were removed with the rest of the ulpextract machinery. StealerCredsReader
# now reads from extracted_records via CH's URL functions; existing
# <db>.creds rows stay on disk as a cold tombstone until the operator
# runs DROP TABLE <db>.creds by hand.


def _storage_policy_setting() -> str:
    """`storage_policy='<name>'` SETTINGS fragment (no SETTINGS keyword) when
    EYENET_CLICKHOUSE_STORAGE_POLICY is set, empty string otherwise. Kept dumb on
    purpose: CH itself validates the name at CREATE TABLE and fails loud if the
    policy does not exist. Callers that need other settings alongside the policy
    compose this fragment into one SETTINGS clause (see _records_create)."""
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
    return f"storage_policy = '{policy}'"


def _storage_policy_clause() -> str:
    """`SETTINGS storage_policy='<name>'` or empty. Used by the rollup/target
    tables that carry no other table-level settings."""
    s = _storage_policy_setting()
    return f"SETTINGS {s}" if s else ""


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
# Plane base tables. The shared extracted_records is retired in favour of two
# physical planes (credlist firehose / victim) so the victim-plane MVs never
# scan a firehose insert block. Names match the Go sink
# (gotractor/sink/ch.go tableFor). See development/CH_PLANE_SEPARATION_SCOPE.md.
_RECORDS_CREDLIST = "extracted_records_credlist"
_RECORDS_VICTIM = "extracted_records_victim"

# Per-plane ORDER BY. The dedup identity (archive_sha256, rule_id, file_path,
# fields-hash) is preserved in both; credlist PREPENDS rev_host so hierarchy
# pivots (`rev_host LIKE 'cl.%'`) are native primary-key range seeks -- no
# projection, no second copy. rev_host is a function of fields, so prepending it
# changes no dedup grain. The victim plane leads with archive_sha256 for its
# per-(archive, victim) seeks. See development/CH_PLANE_SEPARATION_SCOPE.md +
# CH_NEW_SCHEMAS.md.
_DEDUP_TAIL = "archive_sha256, rule_id, file_path, cityHash64(toString(fields))"
_CREDLIST_ORDER_BY = f"rev_host, {_DEDUP_TAIL}"
_VICTIM_ORDER_BY = _DEDUP_TAIL


def _records_create(table: str, order_by: str) -> str:
    """CREATE for one plane base table. Both planes carry the same columns, the
    host_canon / host_registrable / rev_host MATERIALIZED columns, and the same
    skip indexes (set, host_registrable bloom for EXACT host, 26.x text on
    host_canon for SUBSTRING). Everything is folded into the one CREATE (no ALTER
    migration).

    HIERARCHY (rev_host prefix, all `*.cl`) is served NOT by a projection but by
    the credlist table's own ORDER BY leading with rev_host -- a native
    primary-key range seek at ZERO extra storage (measured strictly better than a
    projection: no second copy, smaller base via rev_host-clustered compression,
    2ms hierarchy count, non-key aggregates granule-pruned). The firehose is
    queried by host, never by archive, so leading with rev_host costs nothing
    there. The VICTIM plane keeps archive-leading order for its per-victim seeks
    (hierarchy on the ~3.3% plane is a cheap scan). Hence the per-plane order_by.

    rev_host is derived from fields, so prepending it to the credlist key never
    changes which rows dedup. table / order_by / db are module-owned, never user
    input."""
    settings_clause = _storage_policy_clause()
    return f"""
    CREATE TABLE IF NOT EXISTS {{db}}.{table}
    (
        archive_sha256   FixedString(64),
        source           LowCardinality(String),
        archive_type     LowCardinality(String) DEFAULT '',
        victim_folder    String,
        file_path        String,
        rule_id          LowCardinality(String),
        family           LowCardinality(String),
        fields           Map(String, String),
        ingested_at      DateTime DEFAULT now(),
        host_canon       String MATERIALIZED {_HOST_CANON_EXPR},
        host_registrable String MATERIALIZED cutToFirstSignificantSubdomain({_HOST_CANON_EXPR}),
        rev_host         String MATERIALIZED arrayStringConcat(arrayReverse(splitByChar('.', {_HOST_CANON_EXPR})), '.'),
        INDEX idx_family family TYPE set(0) GRANULARITY 1,
        INDEX idx_rule_id rule_id TYPE set(0) GRANULARITY 1,
        INDEX idx_archive_type archive_type TYPE set(0) GRANULARITY 1,
        INDEX idx_host_registrable host_registrable TYPE bloom_filter(0.01) GRANULARITY 4,
        INDEX idx_host_text host_canon TYPE text(tokenizer = 'ngrams') GRANULARITY 1
    )
    ENGINE = ReplacingMergeTree(ingested_at)
    ORDER BY ({order_by})
    {settings_clause}
    """  # nosec B608


# Combined read view over BOTH planes. Readers that genuinely span both planes
# (global /search, every by-domain credential/cookie/history/subdomain tab) keep
# `FROM extracted_records` verbatim and still get per-branch bloom pruning on
# host_registrable -- verified live: the predicate pushes down into each UNION
# branch's skip index. It MUST list the MATERIALIZED host cols explicitly, because
# SELECT * drops materialized columns (they would vanish from the view). Victim-
# SCOPED readers deliberately BYPASS this view and read extracted_records_victim
# directly so they never scan the firehose. See CH_PLANE_SEPARATION_SCOPE pt3.
_RECORDS_UNION_VIEW = f"""
    CREATE VIEW IF NOT EXISTS {{db}}.extracted_records AS
    SELECT *, host_canon, host_registrable, rev_host FROM {{db}}.{_RECORDS_CREDLIST}
    UNION ALL
    SELECT *, host_canon, host_registrable, rev_host FROM {{db}}.{_RECORDS_VICTIM}
    """  # noqa: S608  # nosec B608


_RECORDS_COLUMNS = [
    "archive_sha256",
    "source",
    "archive_type",
    "victim_folder",
    "file_path",
    "rule_id",
    "family",
    "fields",
]

# Plane tag is written by gotractor per archive (stealer_victim | flat_credlist,
# see classifyArchiveType in daemon.go) and is the sink's routing key into the
# two plane base tables. Both _records_create tables carry the archive_type
# column + index directly, so no ALTER migration is needed.


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
# Dual MV template (both planes -> one AMT target; see plane-split pt1).
_EXTRACTED_ROWS_PER_FILE_MV = f"""
    CREATE MATERIALIZED VIEW IF NOT EXISTS {{db}}.extracted_rows_per_file_mv{{suffix}}
    TO {{db}}.extracted_rows_per_file AS
    SELECT
        archive_sha256,
        file_path,
        uniqHLL12State({_IDENTITY_TUPLE_DDL}) AS cnt
    FROM {{db}}.{{src}}
    GROUP BY archive_sha256, file_path
    """  # noqa: S608  # nosec B608

# v1.4: extracted_rows_per_file_counts is now a plain VIEW finalizing
# extracted_rows_per_file (incremental AMT) at read, replacing the killed
# REFRESH-EVERY MV + ReplacingMergeTree cache. Same name + column shape
# (archive_sha256, file_path, n) so file-tree/coverage readers keep their
# FROM clause; they only drop the FINAL keyword.
_EXTRACTED_ROWS_PER_FILE_COUNTS_VIEW = """
    CREATE VIEW IF NOT EXISTS {db}.extracted_rows_per_file_counts AS
    SELECT
        archive_sha256,
        file_path,
        uniqHLL12Merge(cnt) AS n
    FROM {db}.extracted_rows_per_file
    GROUP BY archive_sha256, file_path
    """

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
    FROM {{db}}.{_RECORDS_VICTIM}
"""  # noqa: S608  # nosec B608

_VICTIM_PROFILES_MV = f"""
    CREATE MATERIALIZED VIEW IF NOT EXISTS {{db}}.victim_profiles_mv
    TO {{db}}.victim_profiles AS
    {_VICTIM_PROFILES_SELECT_CORE}
    WHERE splitByChar('/', file_path)[2] != ''
    GROUP BY archive_sha256, victim_folder
    """


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
)

# v1.4: victim_counts is now a plain VIEW that finalizes victim_profiles
# (incremental AMT) at read, replacing the killed REFRESH-EVERY MV + its
# ReplacingMergeTree cache (the 5-min full rescan was the O(table) OOM shape).
# victim_profiles is ~40k rows so finalizing per read is ms-cheap, and it is
# ALWAYS fresh (no 5-min lag). Column shape matches the old victim_counts table
# (finalized scalars) so readers keep `FROM victim_counts`; they only drop the
# `FINAL` keyword (a view cannot take FINAL). This is the same body the old
# victim_counts_refresh MV used, minus the now()-refreshed_at cache column.
_VICTIM_COUNTS_VIEW = """
    CREATE VIEW IF NOT EXISTS {db}.victim_counts AS
    SELECT
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
        max(first_wallet_family) AS first_wallet_family
    FROM {db}.victim_profiles
    GROUP BY archive_sha256, victim_folder
    """


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

# host_canon / host_registrable are MATERIALIZED columns + the bloom index are
# folded directly into both plane base tables by _records_create (they used to be
# added here via ALTER on the single table). _HOST_CANON_EXPR above is the shared
# expression both tables compute.

# v1.3.6 by-domain flat-counts sibling for /v1/stealer/by-domain/{domain}/summary.
# Same ReplacingMergeTree + REFRESHABLE MV pattern as victim_counts and
# extracted_rows_per_file_counts. Hero card reads one row from here with FINAL
# (cheap, 45ms warm on prod). Deep tabs (credentials / cookies / autofills /
# history / subdomains) hit extracted_records directly, scoped by
# host_registrable + bloom filter. Dedup grains match the deep-tab queries
# (url+login+password for creds, url+name for cookies, etc.) so hero numbers
# agree with per-tab pagination totals.
# v1.3.12.2: converted from refreshable ReplacingMergeTree (full rebuild
# every 5 minutes, OOMed at 7.5 GiB over 157M rows) to incremental
# AggregatingMergeTree. Every INSERT block adds per-group HLL12 state deltas;
# CH merges them in background per host_registrable. Aggregation state is tiny
# (HLL12 ~2.5 KB fixed) and bounded, so there is no corpus-wide memory pressure.
# live_cookie_count / autofill_count / indicator_hit_count were dropped from the
# table -- the first is time-dependent (now() drifts) and the last two were
# constants. The summary endpoint computes live_cookie_count on demand with the
# host_registrable bloom filter.
#
# Plane split: this target spans BOTH planes (combolist = firehose creds AND
# browser_passwords/windows_credentials = victim creds), so it is fed by a MV
# PAIR, one per base table, into this one AggregatingMergeTree. Both MVs run the
# byte-identical SELECT so their states merge. See CH_PLANE_SEPARATION_SCOPE pt1.
_BY_DOMAIN_COUNTS_TABLE = """
    CREATE TABLE IF NOT EXISTS {db}.by_domain_counts
    (
        host_registrable             String,
        victim_count_state           AggregateFunction(uniqHLL12, Tuple(FixedString(64), String)),
        archive_count_state          AggregateFunction(uniqHLL12, FixedString(64)),
        first_seen_at                SimpleAggregateFunction(min, DateTime),
        last_seen_at                 SimpleAggregateFunction(max, DateTime),
        credential_count_state       AggregateFunction(uniqHLL12, Tuple(String, String, String)),
        all_cookie_count_state       AggregateFunction(uniqHLL12, Tuple(String, String)),
        history_count_state          AggregateFunction(uniqHLL12, String),
        localstorage_jwt_count_state AggregateFunction(uniqHLL12, String)
    )
    ENGINE = AggregatingMergeTree
    ORDER BY host_registrable
    {storage_policy_clause}
    """
# Dual-source MV template. {suffix} differentiates the per-plane MV names
# ('' for credlist, '_victim' for victim); {src} is the base table. Body is
# identical across both so AggregatingMergeTree merges the states.
_BY_DOMAIN_COUNTS_MV = """
    CREATE MATERIALIZED VIEW IF NOT EXISTS {db}.by_domain_counts_mv{suffix}
    TO {db}.by_domain_counts
    AS SELECT
        host_registrable,
        uniqHLL12StateIf((archive_sha256, victim_folder),
          family IN ('browser_passwords','windows_credentials',
                     'firefox_logins','combolist')) AS victim_count_state,
        uniqHLL12StateIf(archive_sha256,
          family IN ('browser_passwords','windows_credentials',
                     'firefox_logins','combolist')
          OR family IN ('cookies','victim_cookies')) AS archive_count_state,
        min(ingested_at) AS first_seen_at,
        max(ingested_at) AS last_seen_at,
        uniqHLL12StateIf((fields['url'], fields['user'], fields['password']),
          family IN ('browser_passwords','windows_credentials',
                     'firefox_logins','combolist')) AS credential_count_state,
        -- v1.3.10: cookies store identity as (cookie_domain, cookie_name).
        -- The live-cookie predicate on fromUnixTimestamp(...) > now() lives
        -- at read time (see query_by_domain.summary); here we aggregate ALL
        -- cookies seen, because the AggregatingMergeTree cannot carry a
        -- now()-dependent filter without re-aggregating every tick.
        uniqHLL12StateIf((trim(LEADING '.' FROM fields['cookie_domain']),
                          coalesce(nullIf(fields['cookie_name'], ''), fields['name'])),
          family IN ('cookies','victim_cookies')) AS all_cookie_count_state,
        -- v1.3.10: history rule emits fields['visit_url'], not ['url'].
        -- visit_downloads still uses 'url' so we coalesce both.
        uniqHLL12StateIf(coalesce(nullIf(fields['visit_url'], ''), fields['url']),
          family IN ('victim_history','victim_downloads')) AS history_count_state,
        uniqHLL12StateIf(fields['value'],
          rule_id = 'localstorage_jwt_candidates') AS localstorage_jwt_count_state
    FROM {db}.{src}
    WHERE host_registrable != ''
    GROUP BY host_registrable
    """

# v1.4 per-domain per-victim sibling, REBUILT as an incremental AggregatingMergeTree.
# Backs the Domain-View Victims/Autofills/Antiviruses/Samples tabs: the victim POOL
# for a domain (distinct archive+victim at host_registrable) plus per-victim
# domain-scoped cred/cookie counts. The predecessor was a REFRESH-EVERY MV that
# full-rescanned extracted_records JOIN victim_counts every 5 min = the firehose-
# scale OOM (code 241 at 3.73 GiB). Proven on the 2.3B poc: the incremental MV
# stays ~1.54 GiB/block under the 4 GiB cap and reads ~1100x faster than a live
# scan. Populates from the reindex (MV exists day 0, NO backfill). Enrichment
# (country/build_version/loader_md5) is JOINed from victim_counts (the view over
# victim_profiles) at READ time -- an incremental MV cannot carry that cross-row
# join, and keeping it out means no reprocess when enrichment logic changes.
# Keyed/grouped on the victim_folder COLUMN, which equals splitByChar('/',
# file_path)[2] (verified) so it matches victim_counts for the read-time join.
_BY_DOMAIN_VICTIM_COUNTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS {db}.by_domain_victim_counts
    (
        host_registrable   String,
        archive_sha256     FixedString(64),
        victim_folder      String,
        cred_count_state   AggregateFunction(uniqHLL12, Tuple(String, String, String)),
        cookie_count_state AggregateFunction(uniqHLL12, Tuple(String, String)),
        first_seen_at      SimpleAggregateFunction(min, DateTime),
        last_seen_at       SimpleAggregateFunction(max, DateTime)
    )
    ENGINE = AggregatingMergeTree
    ORDER BY (host_registrable, archive_sha256, victim_folder)
    {storage_policy_clause}
    """,
    """
    CREATE MATERIALIZED VIEW IF NOT EXISTS {db}.by_domain_victim_counts_mv
    TO {db}.by_domain_victim_counts
    AS SELECT
        host_registrable,
        archive_sha256,
        victim_folder,
        uniqHLL12StateIf((fields['url'], fields['user'], fields['password']),
          family IN ('browser_passwords','windows_credentials',
                     'firefox_logins','combolist')) AS cred_count_state,
        uniqHLL12StateIf((fields['url'], fields['name']),
          family IN ('cookies','victim_cookies')) AS cookie_count_state,
        min(ingested_at) AS first_seen_at,
        max(ingested_at) AS last_seen_at
    FROM {db}.extracted_records_victim
    WHERE host_registrable != ''
    GROUP BY host_registrable, archive_sha256, victim_folder
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
#
# The global per-host leaderboard (stats_rollup_host) was DROPPED: a
# full-corpus GROUP BY host over millions of registrable domains OOMed the
# 4 GiB per-query cap on backfill, and the "top hosts" number is vanity
# (google/facebook/roblox for every corpus). See CH_ROLLUP_PLANES_REVISED
# D1. _HOST_EXPR_DDL is retained: count_host/search still use it at read.
#
# The SCHEME/TLD expressions must stay in lock-step with the Python
# reader (eyenet/stealer/query.py StealerCredsReader._{SCHEME,TLD}_EXPR)
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
# Dual-source MV templates (one target each, fed by a credlist + victim MV
# pair; see CH_PLANE_SEPARATION_SCOPE pt1). {suffix} differentiates the per-plane
# MV name, {src} the base table; bodies are byte-identical so the AMT states merge.
_STATS_ROLLUP_TOTALS_MV = f"""
    CREATE MATERIALIZED VIEW IF NOT EXISTS {{db}}.stats_rollup_totals_mv{{suffix}}
    TO {{db}}.stats_rollup_totals AS
    SELECT
        'all' AS bucket,
        uniqHLL12State({_IDENTITY_TUPLE_DDL}) AS total_creds,
        uniqHLL12State(({_HOST_EXPR_DDL}, fields['user'], fields['password'])) AS unique_creds,
        uniqHLL12State({_HOST_EXPR_DDL}) AS distinct_hosts
    FROM {{db}}.{{src}}
    WHERE {_STATS_WHERE}
    GROUP BY bucket
    """  # noqa: S608  # nosec B608
_STATS_ROLLUP_SCHEME_MV = f"""
    CREATE MATERIALIZED VIEW IF NOT EXISTS {{db}}.stats_rollup_scheme_mv{{suffix}}
    TO {{db}}.stats_rollup_scheme AS
    SELECT
        {_SCHEME_EXPR_DDL} AS scheme,
        uniqHLL12State({_IDENTITY_TUPLE_DDL}) AS cnt
    FROM {{db}}.{{src}}
    WHERE {_STATS_WHERE} AND notEmpty({_SCHEME_EXPR_DDL})
    GROUP BY scheme
    """  # noqa: S608  # nosec B608
_STATS_ROLLUP_TLD_MV = f"""
    CREATE MATERIALIZED VIEW IF NOT EXISTS {{db}}.stats_rollup_tld_mv{{suffix}}
    TO {{db}}.stats_rollup_tld AS
    SELECT
        {_TLD_EXPR_DDL} AS tld,
        uniqHLL12State({_IDENTITY_TUPLE_DDL}) AS cnt
    FROM {{db}}.{{src}}
    WHERE {_STATS_WHERE} AND notEmpty({_TLD_EXPR_DDL})
    GROUP BY tld
    """  # noqa: S608  # nosec B608
# Plane-agnostic target tables (one each; fed by the dual MV pairs above).
_STATS_ROLLUP_TABLES: tuple[str, ...] = (
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
)
# Dual MV templates, applied once per plane (credlist + victim) in ensure_schema.
_STATS_ROLLUP_MVS: tuple[str, ...] = (
    _STATS_ROLLUP_TOTALS_MV,
    _STATS_ROLLUP_SCHEME_MV,
    _STATS_ROLLUP_TLD_MV,
)


# v1.3.1 parse-failures acceleration. GET /v1/stealer/failures was doing
# a LEFT JOIN against a FULL scan of extracted_records (3.6M rows FINAL,
# GROUP BY file_path) just to know which files had at least one record.
# Observed 4.2s wall time for a 25-row page on prod. Fix: maintain a
# tiny ReplacingMergeTree of the DISTINCT file_paths that have ever
# emitted an extracted record. The reader anti-joins against this
# instead of the raw records table.
# Dual MV template (both planes -> one ReplacingMergeTree target; the file-path
# inventory spans both planes). Applied per-plane in ensure_schema.
_EXTRACTED_FILE_PATHS_MV = """
    CREATE MATERIALIZED VIEW IF NOT EXISTS {db}.extracted_file_paths_mv{suffix}
    TO {db}.extracted_file_paths AS
    SELECT file_path
    FROM {db}.{src}
    """

# Target tables (plane-agnostic) + the VICTIM-ONLY MVs for this group, applied
# through the generic loop. The two DUAL MVs (extracted_file_paths_mv,
# extracted_rows_per_file_mv) are applied per-plane separately in ensure_schema;
# they are NOT in this tuple because the loop knows only db + storage_policy.
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
    # v1.3.1 per-archive per-file row counts. Backs file_tree() and the
    # per-victim coverage computation. AggregatingMergeTree keyed on
    # (archive, file_path) so a per-archive lookup is a direct index seek.
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
    # v1.3.1 per-victim rule-id set. Backs the artifact drawer's fired_rule_ids
    # resolution. ReplacingMergeTree keyed on (archive, victim_folder, rule_id).
    # Victim-only MV: sources the victim plane.
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
    FROM {db}.extracted_records_victim
    WHERE splitByChar('/', file_path)[2] != ''
    """,
    # v1.3.1 per-victim records index. Backs the artifact drawer's Credentials /
    # Cookies / System tabs. ORDER BY (archive, victim_folder, rule_id, file_path)
    # makes the common filter a direct index seek. Victim-only MV.
    # (Open pt 2: on the split victim table this could become a projection; kept
    # as a copy MV for the first cut -- ANTI deferred the projection.)
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
    FROM {db}.extracted_records_victim
    WHERE splitByChar('/', file_path)[2] != ''
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
    FROM {db}.extracted_records_victim
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
    FROM {db}.extracted_records_victim
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
    FROM {db}.extracted_records_victim
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
    FROM {db}.extracted_records_victim
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
    FROM {db}.extracted_records_victim
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
    FROM {db}.extracted_records_victim
    WHERE rule_id = 'history_webmail_identity'
      AND fields['webmail_email'] LIKE '%@%'
      AND splitByChar('/', file_path)[2] != ''
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

    # Dual MV templates, applied once per base plane into their single shared
    # target. Body is byte-identical across planes so the AMT merges the states.
    _DUAL_MVS: tuple[str, ...] = (
        _BY_DOMAIN_COUNTS_MV,
        _EXTRACTED_FILE_PATHS_MV,
        _EXTRACTED_ROWS_PER_FILE_MV,
        *_STATS_ROLLUP_MVS,
    )
    _PLANES: tuple[tuple[str, str], ...] = (
        (_RECORDS_CREDLIST, ""),
        (_RECORDS_VICTIM, "_victim"),
    )
    # Every MV on the records plane -- dropped one-time when migrating a
    # pre-split deployment so the new CREATEs bind to the plane tables instead
    # of no-opping against the old MVs on extracted_records.
    _OLD_PLANE_MVS: tuple[str, ...] = (
        "victim_profiles_mv",
        "by_domain_victim_counts_mv",
        "extracted_rules_per_victim_mv",
        "extracted_records_by_victim_mv",
        "victim_domains_cookies_mv",
        "victim_domains_creds_mv",
        "victim_domains_history_mv",
        "victim_domains_downloads_mv",
        "victim_domains_localstorage_mv",
        "victim_domains_webmail_mv",
        "by_domain_counts_mv",
        "stats_rollup_totals_mv",
        "stats_rollup_scheme_mv",
        "stats_rollup_tld_mv",
        "extracted_file_paths_mv",
        "extracted_rows_per_file_mv",
    )

    def ensure_schema(self) -> None:
        client = self._connect()
        db = self._db
        spc = _storage_policy_clause()
        client.command(_CREATE_DB.format(db=db))

        # One-time plane-split migration. If the OLD single-plane
        # extracted_records base table is present, this is a pre-split
        # deployment: drop its MVs so the new per-plane MVs below bind to the
        # plane tables (CREATE IF NOT EXISTS would otherwise no-op against the
        # old MVs), then drop the old base table. Gated on the old table's
        # existence so it fires exactly once -- NOT every boot (a blind drop
        # every boot would wipe the tables on every restart). A from-zero
        # reindex repopulates the plane tables; this is not a data migration.
        # See development/CH_PLANE_SEPARATION_SCOPE.md.
        self._migrate_old_single_plane(client, db)

        # Two plane base tables. Same columns + indexes; per-plane ORDER BY
        # (credlist leads with rev_host for free hierarchy range-seeks, victim
        # leads with archive_sha256 for per-victim seeks).
        client.command(_records_create(_RECORDS_CREDLIST, _CREDLIST_ORDER_BY).format(db=db))
        client.command(_records_create(_RECORDS_VICTIM, _VICTIM_ORDER_BY).format(db=db))
        # Combined read view for both-plane readers (search, by-domain tabs).
        # Victim-scoped readers bypass it and hit extracted_records_victim.
        client.command(_RECORDS_UNION_VIEW.format(db=db))

        # Victim-plane rollups (targets + victim-only MVs, source the victim plane).
        for stmt in _VICTIM_PROFILES:
            client.command(stmt.format(db=db, storage_policy_clause=spc))
        # victim_counts: a VIEW over victim_profiles (incremental AMT) finalized
        # at read -- always fresh, no rescan (CH_ROLLUP_PLANES_REVISED D2).
        client.command(_VICTIM_COUNTS_VIEW.format(db=db))
        for stmt in _VICTIM_DOMAINS:
            client.command(stmt.format(db=db, storage_policy_clause=spc))
        for stmt in _MONITORED_DOMAINS:
            client.command(stmt.format(db=db))

        # Credential/shared-plane target tables (plane-agnostic).
        for stmt in _STATS_ROLLUP_TABLES:
            client.command(stmt.format(db=db, storage_policy_clause=spc))
        # parse-failures + per-file/per-victim targets and victim-only MVs.
        for stmt in _EXTRACTED_PATHS:
            client.command(stmt.format(db=db, storage_policy_clause=spc))
        # extracted_rows_per_file_counts: a VIEW finalizing the AMT at read.
        client.command(_EXTRACTED_ROWS_PER_FILE_COUNTS_VIEW.format(db=db))
        # by_domain_counts target (dual-sourced) + by_domain_victim_counts
        # (victim-only, table + MV).
        client.command(_BY_DOMAIN_COUNTS_TABLE.format(db=db, storage_policy_clause=spc))
        for stmt in _BY_DOMAIN_VICTIM_COUNTS:
            client.command(stmt.format(db=db, storage_policy_clause=spc))

        # Dual-source MVs: each applied once per base plane into its one target.
        for template in self._DUAL_MVS:
            for src, suffix in self._PLANES:
                client.command(template.format(db=db, src=src, suffix=suffix))

    def _migrate_old_single_plane(self, client: Any, db: str) -> None:
        """Retire a pre-split deployment's shared extracted_records world, once.
        No-op on a fresh install and on every boot after the migration."""
        rows = client.query(
            "SELECT 1 FROM system.tables "  # noqa: S608  # nosec B608
            f"WHERE database = '{db}' AND name = 'extracted_records' "
            "AND engine LIKE '%MergeTree%'"
        ).result_rows
        if not rows:
            return
        for mv in self._OLD_PLANE_MVS:
            client.command(f"DROP VIEW IF EXISTS {db}.{mv}")
        client.command(f"DROP TABLE IF EXISTS {db}.extracted_records")

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
            client,
            db=self._db,
            mv_name=mv_name,
            target_name=target_name,
            sentinel=sentinel,
        )

    def insert_rows(self, rows: Iterable[list[Any]]) -> int:
        batch: list[list[Any]] = list(rows)
        if not batch:
            return 0
        client = self._connect()
        # Route each row to its plane base table by archive_type (column index 2
        # in _RECORDS_COLUMNS), matching the Go sink's tableFor. gotractor is the
        # primary data plane ([[feedback-dont-pipe-go-data-through-python]]); this
        # path is the legacy/fallback insert and stays correct by routing the same
        # way. Unknown tags fall to the firehose, the safe bucket.
        victim = [r for r in batch if r[2] == "stealer_victim"]
        credlist = [r for r in batch if r[2] != "stealer_victim"]
        for table, part in ((_RECORDS_CREDLIST, credlist), (_RECORDS_VICTIM, victim)):
            if part:
                client.insert(f"{self._db}.{table}", part, column_names=_RECORDS_COLUMNS)
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
