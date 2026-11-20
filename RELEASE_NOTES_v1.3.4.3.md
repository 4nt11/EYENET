# v1.3.4.3: the artifacts endpoint stops 500ing

## tl;dr

`/v1/stealer/artifacts` (and everything else reading `victim_profiles`) was
500ing with ClickHouse `code: 241 Memory limit exceeded` after the overnight
reindex. Root cause: `FROM victim_profiles FINAL` merges every part's
`AggregateFunction(uniqExact, ...)` state in memory per query. On Wasabi-backed
parts holding uniqExact sets of hundreds of thousands of distinct identity
tuples per big victim, a single column read wants 2.3+ GiB.

Fix: a sibling `victim_counts` table (ReplacingMergeTree, plain `UInt64`)
refreshed every 5 minutes from `victim_profiles` by a REFRESHABLE MV. The API
read paths move off the heavy states entirely.

Measured on prod (20,884 keys, 12 parts, Wasabi S3):

|                        | before      | after     |
|------------------------|-------------|-----------|
| unfiltered page        | 1.10 s      | **16 ms** |
| `has_wallet=1` page    | OOM 500     | **10 ms** |
| `has_wallet=0` page    | 51 ms       | **12 ms** |
| memory                 | 2.33 GB OOM | nowhere near cap |

Roughly 110x on the unfiltered path, from OOM-500 to usable on the wallet
filter.

## What changed

### `stealer.victim_counts` + refreshable MV

New flat-counts sibling table. ReplacingMergeTree keyed on
`(archive_sha256, victim_folder)` with `refreshed_at` as the version column.
Columns are plain `UInt64` counts + plain typed `max` columns, no aggregate
states. Bootstrap DDL added in `eyenet/stealer/clickhouse.py` and runs via
`ensure_schema()` on service start; the CREATE calls carry
`allow_experimental_refreshable_materialized_view = 1` per-command because
24.8 gates refreshable MVs behind the flag.

`victim_counts_refresh` runs every 5 minutes. It does the heavy
`uniqExactMerge` over the whole `victim_profiles` table once per cycle in the
background, with `optimize_aggregation_in_order = 1` and a
`max_bytes_before_external_group_by = 1 GiB` spill backstop so the refresh
itself never hits the server cap. First prod refresh: 66 seconds, 23,336
input rows, 20,884 output rows.

API freshness is up to 5 minutes stale. Acceptable for an operator UI.

### `list_cards()` and `detail()` rewritten

Both now read `FROM victim_counts FINAL` with plain `WHERE`. The two-stage
CTE, the `GROUP BY + uniqExactMerge`, and the semantic-split `HAVING` for
derived flags are all gone. 50 lines down to 20.

### ClickHouse profile override

`deploy/docker/clickhouse/users.d/zz-eyenet-mem-cap.xml` now ships in the
repo and is mounted into the clickhouse container at
`/etc/clickhouse-server/users.d`. Two settings on the `default` profile:

- `max_memory_usage = 2_500_000_000`: per-query cap. Prevents one heavy
  SELECT from eating the full 3.6 GiB server budget and starving concurrent
  gotractor flushes with `code: 241`. Headroom of ~1.1 GiB for ingest.
- `allow_experimental_refreshable_materialized_view = 1`: gates the
  refreshable MV above.

Previously the overrides existed only inside the running container (we
hot-wrote them while debugging). Baking them in means a `compose down + up`
no longer loses them.

## Research credit

The semantic-split and two-stage CTE path (now removed in favour of the
sibling-table approach) came from a Fable second-opinion pass that caught
one correctness bug: pre-GROUP `WHERE has_wallet = 0` would return victims
whose merged truth is 1, because a single archive can land in multiple
insert blocks with different `has_wallet` values. A follow-up research pass
confirmed the sibling-table pattern as the proper architectural fix.

## Deploy notes

The CH table and MV already exist on prod from the live debugging session;
`ensure_schema()`'s CREATE statements are idempotent and will no-op on
redeploy. The compose mount for `users.d` is new, so the clickhouse
container will pick up the override file from disk instead of the hot-
written copy.

No schema migration risk: `victim_profiles` is untouched and keeps its
exact uniqExactState columns; it is now an internal detail the MV reads to
feed `victim_counts`.

## Follow-ups (not in this release)

- Dedicated `_summary` sibling pattern for other heavy aggregate tables if
  we hit similar FINAL memory cliffs elsewhere.
- A `SYSTEM REFRESH VIEW` hook exposed to ops so a manual force-refresh
  after a backfill does not wait up to 5 minutes.
