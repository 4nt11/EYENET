# CH rollup: uniqExact to uniqHLL12 swap

Status: SCOPED, VERIFIED, EXECUTION-READY. Target release v1.3.12.1.

## TL;DR

`stealer.stats_rollup_totals.total_creds` is
`AggregateFunction(uniqExact, Tuple(FixedString(64), LowCardinality(String),
String, UInt64))`. uniqExact keeps every unique value in a hash set, so the
state size is linear in cardinality. On prod, with 16.68 M records and more
coming, the state hit 740 MiB on disk and triggers code 241 (memory limit
exceeded) on every merge and even on the single-scalar read that feeds the
dashboard stat tile. The same uniqExact pattern bleeds into FOUR sibling
aggregates: `stats_rollup_host`, `stats_rollup_scheme`, `stats_rollup_tld`,
and `extracted_rows_per_file` (smaller today, same failure shape tomorrow).
All five get swapped in one release.

Target function: `uniqHLL12`. Fixed ~2.5 KB state per bucket regardless of
cardinality, ~2.5% error. These feed dashboard stat tiles, not evidence;
precision loss is fine, state size collapse is not.

Fix: swap uniqExact for uniqHLL12. State drops from gigabytes to a fixed
~2.5 KiB per bucket, ~2.5% error on dashboard counters. While the target
tables are being rebuilt we also move unique_creds, distinct_hosts (today
`uniq`) to `uniqHLL12` for one coherent "all stats use HLL12" decision.

## Verification (2026-11-21, prod, during v1.3.12.0 reindex)

Captured in `/tmp/ch_pain_probe.log` and `/tmp/ch_verify_claim.log` on
xmart-eyenet; scripts live in the session scratchpad.

| Probe | Result |
|---|---|
| Max merge peak RAM on stats_rollup_totals | 3.70 GiB (104 merges in 1h, avg 627 MiB) |
| On-disk state size (9 parts, 1 logical row) | 740 MiB total, biggest part 394 MiB |
| Scalar read `uniqExactMerge(total_creds)` | OOM at 3.90 GiB (dashboard tile is unservable) |
| Source cardinality probe | OOM at 3.87 GiB (can't even COUNT the exact set) |
| Code 241 events | 4 in 10 min on one MV |

Context: the CH container has `--memory 4GiB` (cgroup); per-query cap is
2.5 GiB after the 2026-11-21 live patch (cc9aae5). Even with 1.1 GiB
headroom, stats_rollup_totals alone wants 3.70 GiB per merge.

## Code changes

Two files. Both tiny.

### `eyenet/stealer/clickhouse.py`

Mechanical rename across the file:

- `uniqExactState(...)` to `uniqHLL12State(...)` (MV bodies + one-shot backfill).
- `AggregateFunction(uniqExact, ...)` to `AggregateFunction(uniqHLL12, ...)` (target columns).
- Existing `uniqState(...)` on `unique_creds` / `distinct_hosts` to `uniqHLL12State(...)`.
- Existing `AggregateFunction(uniq, ...)` on those columns to `AggregateFunction(uniqHLL12, ...)`.

Affected MVs and their target tables: `stats_rollup_totals`, `stats_rollup_host`,
`stats_rollup_scheme`, `stats_rollup_tld`, `extracted_rows_per_file`.

Expected diff shape:

```
-        uniqExactState({_IDENTITY_TUPLE_DDL}) AS total_creds,
+        uniqHLL12State({_IDENTITY_TUPLE_DDL}) AS total_creds,
...
-        total_creds    AggregateFunction(uniqExact, {_IDENTITY_TUPLE_TYPE}),
+        total_creds    AggregateFunction(uniqHLL12, {_IDENTITY_TUPLE_TYPE}),
...
-        unique_creds   AggregateFunction(uniq, Tuple(String, String, String)),
+        unique_creds   AggregateFunction(uniqHLL12, Tuple(String, String, String)),
```

### `eyenet/stealer/query.py`

- Line 167: `uniqExactMerge(total_creds)` to `uniqHLL12Merge(total_creds)`.
- Existing `uniqMerge(unique_creds)` and `uniqMerge(distinct_hosts)` to
  `uniqHLL12Merge(...)`.
- Line 158 comment: the "~1% error" note becomes "~2.5% error (uniqHLL12)".

Nothing else reads these rollups with uniqExact or uniq semantics
(grepped 2026-11-21).

## Live-prod migration (CH side)

CH cannot `ALTER COLUMN TYPE` across aggregate functions. The target tables
must be rebuilt. Order matters because the MV writes into the target.

Steps (one-shot, safe under the current reindex if executed between archive
boundaries; no need to pause gotractor):

All five MV bodies and target column types below are copied verbatim
from live prod DDL (2026-11-21), uniqExact (and the two existing uniq
columns on stats_rollup_totals) swapped for uniqHLL12. Do not re-shape
them: coalesce chains and WHERE clauses match the code path.

```sql
-- 1) Kill the MVs so no new writes land during swap.
DROP TABLE IF EXISTS stealer.stats_rollup_totals_mv;
DROP TABLE IF EXISTS stealer.stats_rollup_host_mv;
DROP TABLE IF EXISTS stealer.stats_rollup_scheme_mv;
DROP TABLE IF EXISTS stealer.stats_rollup_tld_mv;
DROP TABLE IF EXISTS stealer.extracted_rows_per_file_mv;

-- 2) Rename old target tables out of the way (keep for 24h rollback window;
--    the states are unreadable on this box anyway but the names free up).
RENAME TABLE stealer.stats_rollup_totals     TO stealer.stats_rollup_totals_old,
             stealer.stats_rollup_host       TO stealer.stats_rollup_host_old,
             stealer.stats_rollup_scheme     TO stealer.stats_rollup_scheme_old,
             stealer.stats_rollup_tld        TO stealer.stats_rollup_tld_old,
             stealer.extracted_rows_per_file TO stealer.extracted_rows_per_file_old;

-- 3) Recreate targets with uniqHLL12 instead of uniqExact / uniq.
CREATE TABLE stealer.stats_rollup_totals (
  bucket LowCardinality(String),
  total_creds    AggregateFunction(uniqHLL12, Tuple(FixedString(64), LowCardinality(String), String, UInt64)),
  unique_creds   AggregateFunction(uniqHLL12, Tuple(String, String, String)),
  distinct_hosts AggregateFunction(uniqHLL12, String)
) ENGINE = AggregatingMergeTree ORDER BY bucket
SETTINGS storage_policy = 'wasabi_primary', index_granularity = 8192;

CREATE TABLE stealer.stats_rollup_host (
  host String,
  cnt  AggregateFunction(uniqHLL12, Tuple(FixedString(64), LowCardinality(String), String, UInt64))
) ENGINE = AggregatingMergeTree ORDER BY host
SETTINGS storage_policy = 'wasabi_primary', index_granularity = 8192;

CREATE TABLE stealer.stats_rollup_scheme (
  scheme LowCardinality(String),
  cnt    AggregateFunction(uniqHLL12, Tuple(FixedString(64), LowCardinality(String), String, UInt64))
) ENGINE = AggregatingMergeTree ORDER BY scheme
SETTINGS storage_policy = 'wasabi_primary', index_granularity = 8192;

CREATE TABLE stealer.stats_rollup_tld (
  tld LowCardinality(String),
  cnt AggregateFunction(uniqHLL12, Tuple(FixedString(64), LowCardinality(String), String, UInt64))
) ENGINE = AggregatingMergeTree ORDER BY tld
SETTINGS storage_policy = 'wasabi_primary', index_granularity = 8192;

CREATE TABLE stealer.extracted_rows_per_file (
  archive_sha256 FixedString(64),
  file_path      String,
  cnt            AggregateFunction(uniqHLL12, Tuple(FixedString(64), LowCardinality(String), String, UInt64))
) ENGINE = AggregatingMergeTree ORDER BY (archive_sha256, file_path)
SETTINGS storage_policy = 'wasabi_primary', index_granularity = 8192;

-- 4) Recreate MVs with uniqHLL12State (bodies verbatim from live DDL 2026-11-21).
CREATE MATERIALIZED VIEW stealer.stats_rollup_totals_mv
TO stealer.stats_rollup_totals AS
SELECT
  'all' AS bucket,
  uniqHLL12State((archive_sha256, rule_id, file_path, cityHash64(toString(fields)))) AS total_creds,
  uniqHLL12State((lower(coalesce(nullIf(domain(fields['url']), ''),
                                 nullIf(domain(fields['host']), ''),
                                 nullIf(fields['host'], ''), '')),
                  fields['login'], fields['password'])) AS unique_creds,
  uniqHLL12State(lower(coalesce(nullIf(domain(fields['url']), ''),
                                nullIf(domain(fields['host']), ''),
                                nullIf(fields['host'], ''), ''))) AS distinct_hosts
FROM stealer.extracted_records
WHERE (family IN ('browser_passwords', 'windows_credentials', 'firefox_logins', 'combolist'))
  AND (notEmpty(fields['url']) OR notEmpty(fields['host']))
GROUP BY bucket;

CREATE MATERIALIZED VIEW stealer.stats_rollup_host_mv
TO stealer.stats_rollup_host AS
SELECT
  lower(coalesce(nullIf(domain(fields['url']), ''),
                 nullIf(domain(fields['host']), ''),
                 nullIf(fields['host'], ''), '')) AS host,
  uniqHLL12State((archive_sha256, rule_id, file_path, cityHash64(toString(fields)))) AS cnt
FROM stealer.extracted_records
WHERE (family IN ('browser_passwords', 'windows_credentials', 'firefox_logins', 'combolist'))
  AND (notEmpty(fields['url']) OR notEmpty(fields['host']))
  AND notEmpty(lower(coalesce(nullIf(domain(fields['url']), ''),
                              nullIf(domain(fields['host']), ''),
                              nullIf(fields['host'], ''), '')))
GROUP BY host;

CREATE MATERIALIZED VIEW stealer.stats_rollup_scheme_mv
TO stealer.stats_rollup_scheme AS
SELECT
  lower(coalesce(nullIf(fields['scheme'], ''),
                 nullIf(protocol(fields['url']), ''), '')) AS scheme,
  uniqHLL12State((archive_sha256, rule_id, file_path, cityHash64(toString(fields)))) AS cnt
FROM stealer.extracted_records
WHERE (family IN ('browser_passwords', 'windows_credentials', 'firefox_logins', 'combolist'))
  AND (notEmpty(fields['url']) OR notEmpty(fields['host']))
  AND notEmpty(lower(coalesce(nullIf(fields['scheme'], ''),
                              nullIf(protocol(fields['url']), ''), '')))
GROUP BY scheme;

CREATE MATERIALIZED VIEW stealer.stats_rollup_tld_mv
TO stealer.stats_rollup_tld AS
SELECT
  coalesce(nullIf(fields['tld'], ''),
           nullIf(topLevelDomain(fields['url']), ''),
           nullIf(topLevelDomain(fields['host']), ''), '') AS tld,
  uniqHLL12State((archive_sha256, rule_id, file_path, cityHash64(toString(fields)))) AS cnt
FROM stealer.extracted_records
WHERE (family IN ('browser_passwords', 'windows_credentials', 'firefox_logins', 'combolist'))
  AND (notEmpty(fields['url']) OR notEmpty(fields['host']))
  AND notEmpty(coalesce(nullIf(fields['tld'], ''),
                        nullIf(topLevelDomain(fields['url']), ''),
                        nullIf(topLevelDomain(fields['host']), ''), ''))
GROUP BY tld;

CREATE MATERIALIZED VIEW stealer.extracted_rows_per_file_mv
TO stealer.extracted_rows_per_file AS
SELECT
  archive_sha256,
  file_path,
  uniqHLL12State((archive_sha256, rule_id, file_path, cityHash64(toString(fields)))) AS cnt
FROM stealer.extracted_records
GROUP BY archive_sha256, file_path;
```

Note on `extracted_rows_per_file`: `archive_sha256` and `file_path` are
constants within each GROUP BY bucket, so storing them inside the identity
tuple is pure waste. A cleaner v2 would drop them from the tuple and hash
only `(rule_id, cityHash64(toString(fields)))`. OUT OF SCOPE for this
release: keep the tuple shape intact, swap only the aggregator, zero risk
of silently changing dedup semantics for downstream readers. Revisit in a
dedicated clean-up pass.

### Backfill

This is the one step that costs budget. The backfill reads `extracted_records`
once (currently ~16-30 M rows, growing) and writes three aggregate rows per
bucket.

Backfill the five targets sequentially. Each scan reads `extracted_records`
once; totals + host + scheme + tld share a WHERE predicate so they can
be driven from the same scan via a UNION-ALL-into-null trick if needed,
but the simple serial approach is lazy enough at ~16-30 M rows.

```sql
-- stats_rollup_totals: 1 row ('all')
INSERT INTO stealer.stats_rollup_totals
SELECT
  'all' AS bucket,
  uniqHLL12State((archive_sha256, rule_id, file_path, cityHash64(toString(fields)))),
  uniqHLL12State((lower(coalesce(nullIf(domain(fields['url']),''),
                                 nullIf(domain(fields['host']),''),
                                 nullIf(fields['host'],''), '')),
                  fields['login'], fields['password'])),
  uniqHLL12State(lower(coalesce(nullIf(domain(fields['url']),''),
                                nullIf(domain(fields['host']),''),
                                nullIf(fields['host'],''), '')))
FROM stealer.extracted_records
WHERE family IN ('browser_passwords','windows_credentials','firefox_logins','combolist')
  AND (notEmpty(fields['url']) OR notEmpty(fields['host']))
SETTINGS max_memory_usage = 2000000000, max_bytes_before_external_group_by = 1500000000;

-- stats_rollup_host: N rows (one per host)
INSERT INTO stealer.stats_rollup_host
SELECT
  lower(coalesce(nullIf(domain(fields['url']),''),
                 nullIf(domain(fields['host']),''),
                 nullIf(fields['host'],''), '')) AS host,
  uniqHLL12State((archive_sha256, rule_id, file_path, cityHash64(toString(fields))))
FROM stealer.extracted_records
WHERE family IN ('browser_passwords','windows_credentials','firefox_logins','combolist')
  AND (notEmpty(fields['url']) OR notEmpty(fields['host']))
  AND notEmpty(lower(coalesce(nullIf(domain(fields['url']),''),
                              nullIf(domain(fields['host']),''),
                              nullIf(fields['host'],''), '')))
GROUP BY host
SETTINGS max_memory_usage = 2000000000, max_bytes_before_external_group_by = 1500000000;

-- stats_rollup_scheme: small N
INSERT INTO stealer.stats_rollup_scheme
SELECT
  lower(coalesce(nullIf(fields['scheme'], ''),
                 nullIf(protocol(fields['url']), ''), '')) AS scheme,
  uniqHLL12State((archive_sha256, rule_id, file_path, cityHash64(toString(fields))))
FROM stealer.extracted_records
WHERE (family IN ('browser_passwords','windows_credentials','firefox_logins','combolist'))
  AND (notEmpty(fields['url']) OR notEmpty(fields['host']))
  AND notEmpty(lower(coalesce(nullIf(fields['scheme'], ''),
                              nullIf(protocol(fields['url']), ''), '')))
GROUP BY scheme
SETTINGS max_memory_usage = 2000000000;

-- stats_rollup_tld: small N
INSERT INTO stealer.stats_rollup_tld
SELECT
  coalesce(nullIf(fields['tld'], ''),
           nullIf(topLevelDomain(fields['url']), ''),
           nullIf(topLevelDomain(fields['host']), ''), '') AS tld,
  uniqHLL12State((archive_sha256, rule_id, file_path, cityHash64(toString(fields))))
FROM stealer.extracted_records
WHERE (family IN ('browser_passwords','windows_credentials','firefox_logins','combolist'))
  AND (notEmpty(fields['url']) OR notEmpty(fields['host']))
  AND notEmpty(coalesce(nullIf(fields['tld'], ''),
                        nullIf(topLevelDomain(fields['url']), ''),
                        nullIf(topLevelDomain(fields['host']), ''), ''))
GROUP BY tld
SETTINGS max_memory_usage = 2000000000;

-- extracted_rows_per_file: one row per (archive, file)
INSERT INTO stealer.extracted_rows_per_file
SELECT
  archive_sha256,
  file_path,
  uniqHLL12State((archive_sha256, rule_id, file_path, cityHash64(toString(fields))))
FROM stealer.extracted_records
GROUP BY archive_sha256, file_path
SETTINGS max_memory_usage = 2000000000, max_bytes_before_external_group_by = 1500000000;
```

`max_bytes_before_external_group_by` lets CH spill GROUP BY state to disk.
HLL12 itself is fixed-size so the state is tiny; the GROUP BY on host /
(archive, file) is where the spill helps. Belt and suspenders.

### Verify

After the backfill:

```sql
SELECT 'totals' AS rollup,
       uniqHLL12Merge(total_creds)   AS total,
       uniqHLL12Merge(unique_creds)  AS unique_cred_count,
       uniqHLL12Merge(distinct_hosts) AS host_count
FROM stealer.stats_rollup_totals
UNION ALL SELECT 'host_rows',       count(), 0, 0 FROM stealer.stats_rollup_host
UNION ALL SELECT 'scheme_rows',     count(), 0, 0 FROM stealer.stats_rollup_scheme
UNION ALL SELECT 'tld_rows',        count(), 0, 0 FROM stealer.stats_rollup_tld
UNION ALL SELECT 'file_rows',       count(), 0, 0 FROM stealer.extracted_rows_per_file;
```

Then confirm this query returns in under a second (previously OOMed).
That alone is the proof the swap worked.

### Cleanup (deferred)

Leave the `_old` tables for 24 hours in case we need to reconstruct from
them (we won't; the states are unreadable, but the sheer paranoia is
free). Then:

```sql
DROP TABLE stealer.stats_rollup_totals_old;
DROP TABLE stealer.stats_rollup_host_old;
DROP TABLE stealer.stats_rollup_scheme_old;
DROP TABLE stealer.stats_rollup_tld_old;
DROP TABLE stealer.extracted_rows_per_file_old;
```

## Rollback

Code side: revert v1.3.12.1.

CH side: not meaningfully rollbackable. The old states were unreadable
on this box anyway (every read OOMed). If needed, `RENAME` the `_old`
tables back; the stat tile will resume returning "memory limit exceeded"
errors just as it did before this release.

## Risk notes

- The MV is dropped and recreated. Rows written to `extracted_records`
  during the swap window (between DROP TABLE ... _mv and CREATE MATERIALIZED
  VIEW ... _mv) will NOT trigger the MV. They will be reflected in the
  backfill as long as the backfill runs AFTER the MV is back up; if the
  backfill reads rows that haven't yet been inserted, those rows arrive
  via the live MV. Order: DROP, RENAME, CREATE TABLE, CREATE MV, then
  INSERT backfill. This way: any row inserted after CREATE MV goes
  through BOTH the MV (live) and the backfill (if present at read time).
  The target is AggregatingMergeTree with uniqHLL12State: double-counting
  is harmless (HLL union is idempotent for the same identity).
- Backfill memory ceiling at 2000000000 is intentionally below the
  per-query cap (2500000000) so a single scan does not OOM the box. If
  it still OOMs, raise `max_bytes_before_external_group_by` further and
  accept the spill.
- Reindex can keep running throughout. The MVs feeding extracted_records
  do not block the main-table writes. Worst case, the backfill competes
  with reindex merges for RAM; if that shows up as code 241 on other
  tables, pause the reindex for the ~minute the backfill takes.

## Next

1. Code change (clickhouse.py + query.py): one commit, trivial.
2. Release v1.3.12.1 tag + release notes referencing this doc.
3. Execute the live-prod migration at the first quiet window during the
   reindex (gotractor between archives is ideal; we have 1 M rec/min
   steady so a 30-second pause is invisible).
4. Watch `system.part_log` for the next 10 min: max merge peak RAM on
   stats_rollup_totals should drop to tens of MiB. If it does, this
   story closes and the "batch for shit machines" question (FOLLOWUP.md
   section 1) stays closed too.

## No deferred siblings

All uniqExactState aggregators in the stealer schema (5 total) are swapped
in this release. `extracted_rows_per_file` was initially flagged as
deferred; on inspection it uses the same uniqExactState pattern and is
folded in. The only remaining cleanup is a v2 that drops the redundant
`archive_sha256` and `file_path` fields from its identity tuple (they are
constants within the bucket); that is a dedup-semantics change and belongs
in a dedicated pass, not here.
