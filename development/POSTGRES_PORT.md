# POSTGRES_PORT.md — adding the async Postgres backend

Status: DONE — the single-host stack was cut over from SQLite to Postgres on
2026-10-11. ~10.37M rows moved, both hash chains re-verified on Postgres, ~21
min downtime (one window). The connector (`PostgresRepository`), the parallel
Alembic tree, and the data move were all already landed; this cutover wired the
infra (compose `postgres` + `pgbouncer`), ran the live move, and fixed two gaps
the swap exposed (below). Backend selection is `EYENET_STORAGE_TYPE` (now
defaults to `postgres` in compose; flip to `sqlite` to roll back — the SQLite
DBs in the `eyenet-data` volume are untouched).

This is the phased plan for `PostgresRepository(SQLModelRepository)`, the
parallel Alembic tree, and the one-shot live-DB data move. It assumes the M9
storage abstraction (see `CLAUDE.md` §2) is intact: factory dispatch, flat
`BaseRepository` surface, dialect leaks fenced into the concrete backend.

## 0a. Two gaps the live cutover exposed (don't relearn these the hard way)

1. **Callers hardcode `get_repository(data_dir=cfg.data_dir)`** (20+ CLI sites) —
   a SQLite-only kwarg `PostgresRepository.__init__` rejects, crash-looping every
   service. Fix is one place: `factory.py` now filters kwargs to the chosen
   backend's `__init__` signature (`_accepted`), so Postgres drops `data_dir` and
   reads `EYENET_PG_URL` / `EYENET_PG_DDL_URL` from the env. (The "no caller
   changes" claim held — the fix was in the factory, not the callers.)
2. **The running image must be REBUILT before the swap.** `eyenet:base` ships the
   connector code; an image from before these fixes crash-loops on Postgres. The
   drivers (`asyncpg`/`psycopg`) were already baked in (core deps), but the code
   was stale. Rebuild `eyenet:base` in the prep phase, NOT mid-blackout.

Operational notes: pgbouncer (edoburu) defaults to listen on 5432 — set
`LISTEN_PORT=6432` to match the conventional URL. The DDL/migration path (run at
every service boot via `upgrade_to_head`) MUST bypass the transaction pooler:
`EYENET_PG_URL`→pgbouncer, `EYENET_PG_DDL_URL`→postgres direct. The cutover
orchestrator is `scripts/pg_cutover.py` (snapshot → create DBs → baseline → move
→ verify counts + both hash chains, FAIL LOUD). Measured move: ~10.3M rows in
~9 min via batched executemany — COPY (§2.6) was NOT needed at this scale.

---

## 0. Why (the justification, so future-you does not relitigate it)

Prod ingests many forums + many Telegram channels, all day. That is concurrent
writers across N supervisor-spawned collector processes. SQLite serializes ALL
writers to one at a time (WAL only unblocks readers, not writers). That is the
wall. Postgres MVCC lets the collectors write concurrently.

SQLite stays the DEFAULT backend: tests (in-memory shared-cache), dev, and
fresh small operators. Postgres is the scale-out prod target. Two maintained
worlds, on purpose. See §6 for how to keep the two-tree tax survivable.

**Load-bearing invariant:** the single-writer audit/file-access hash chains are
NOT on the message ingest path today (`put_observation` /
`put_observations_bulk` do not call `append_audit`). Postgres only helps ingest
BECAUSE of this. If anyone slips `append_audit` into the bulk ingest path, the
Postgres advisory-lock serialization (§2.3) re-creates the exact bottleneck we
are fleeing. Guard this in review. Add a test that asserts the bulk ingest
methods emit no audit event.

---

## 1. Dependency

Add `asyncpg` (async driver) and `psycopg[binary]` (sync driver, for the DDL
engine Alembic runs on). Pin both hard per the add-a-dep rule. URL schemes:

- async query engine: `postgresql+asyncpg://user:pw@host:5432/eyenet`
- sync DDL engine:     `postgresql+psycopg://user:pw@host:5432/eyenet`

`pgbouncer` is an ops dependency, not a Python one. See §5.

---

## 2. The override surface — `eyenet/storage/postgres_repo/`

Mirror the `sqlite_repo/` layout: `repository.py`, `database.py`, `migrations/`.
Everything else is inherited from `sqlmodel_repo/`. Six override points.

### 2.1 Engine construction (`database.py` + `__init__`) — EASY

No `cache=shared` / `StaticPool` in-memory trick (SQLite-only). Postgres
main/audit split is **two databases** on one server (`eyenet` + `eyenet_audit`)
OR two schemas. Recommend two databases: keeps the two-engine, two-session
model identical to SQLite and isolates audit at the storage level.

`create_async_engine(url, pool_size=..., max_overflow=...)` — see §5 for sizing.
No in-memory constructor path; Postgres tests use a real server (§4).

### 2.2 `set_cursors_bulk` (upsert) — TRIVIAL

Postgres has the same `INSERT ... ON CONFLICT DO UPDATE`. Swap
`sqlalchemy.dialects.sqlite.insert` for `.postgresql.insert`. Near-identical to
the SQLite override. Dialect import stays in the backend (Rule 1).

### 2.3 Audit chain: `_append_audit_locked` / `_append_chain` — HARD

`BEGIN IMMEDIATE` has no Postgres equivalent. Re-express the single-writer
invariant with a **transaction-scoped advisory lock**:

```python
# inside one transaction on the audit engine:
await conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": AUDIT_LOCK_KEY})
# read last self_hash, compute new self_hash over envelope + prev_hash, INSERT, COMMIT
```

`pg_advisory_xact_lock` auto-releases on commit/rollback — no leak on crash,
unlike a session-level lock. One fixed 64-bit key for the audit chain. The
in-process `asyncio.Lock` stays as the fast path; the advisory lock is the
cross-process serializer (the role `BEGIN IMMEDIATE` played on SQLite).

Chain semantics are unchanged: read tip `self_hash`, hash over envelope +
`prev_hash`, INSERT inside the locked transaction. The hash is content-derived,
so it is dialect-independent.

### 2.4 File-access chain: `_append_file_access_locked` + `_consume_nonce_locked` — HARD

Same advisory-lock pattern, a DIFFERENT lock key (`FILE_ACCESS_LOCK_KEY`), on
the audit engine (the journal lives with audit). `_consume_nonce_locked` runs
inside the same locked transaction, same as the SQLite raw-cursor path. Do 2.3
and 2.4 together — one lock strategy, two write paths.

### 2.5 FTS: `_body_match` / `_fts_query` — MEDIUM

FTS5 virtual table + 3 sync triggers become a **generated `tsvector` column +
GIN index**, maintained by Postgres automatically (no triggers to hand-write):

```sql
ALTER TABLE message ADD COLUMN body_tsv tsvector
  GENERATED ALWAYS AS (to_tsvector('simple', coalesce(body, ''))) STORED;
CREATE INDEX ix_message_body_tsv ON message USING gin (body_tsv);
```

`_body_match` override: `text("message.body_tsv @@ websearch_to_tsquery('simple', :q)")`.
`websearch_to_tsquery` neutralizes operator-input syntax errors the way
`_fts_query` phrase-wrapping does for FTS5, so the input-sanitizing intent
carries over. Use `'simple'` config (no stemming) to match the current
locale-agnostic, substring-ish analyst mental model; revisit per-language later.

### 2.6 `put_observations_bulk` COPY override — the THROUGHPUT one

Row-at-a-time `INSERT` over asyncpg is not the firehose. Override the bulk path
to use `COPY` (asyncpg `copy_records_to_table`), 10-50x over INSERT. This is
where "all day every day" volume lives or dies. Declare the generic
SELECT-then-add version stays on the mixin; the COPY fast path is the Postgres
override. Measure before hand-tuning further.

---

## 3. Migrations — the parallel tree (the real maintenance tax)

Separate tree: `eyenet/storage/postgres_repo/migrations/`, its own `env.py`,
its own `versions/`. Differences from the SQLite tree:

- `render_as_batch=False` — Postgres does real in-place ALTER. No copy-and-move.
- No `_sqlite_compare_type` shim (Postgres enforces `VARCHAR(n)`; real types).
- Fresh `0001_baseline` expressing the raw DDL the Postgres way:
  - FTS5 index + triggers  → the tsvector generated column + GIN index (§2.5)
  - `vector_signature` side-table → native, plus its index
  - partial UNIQUE index (`WHERE retired_at IS NULL`) → native Postgres partial
    index, same predicate
  - native `uuid` / `timestamptz` where SQLite used TEXT affinity
- Same multi-db env pattern (two engines via `config.attributes`), same
  `_RAW_DDL_OBJECTS` exclusion from autogenerate.

The SQLite `0001_baseline` is FROZEN and does NOT port. This is a fresh
baseline. From here, a schema change is a new revision in the tree of whichever
backend that deployment runs. You just froze v0.1.0, so schema churn is about to
drop off a cliff. This is the least-bad time to take on a second tree.

---

## 4. Tests

The `get_repository(in_memory=True)` fast path is SQLite-only. Postgres tests
need a real server. Reuse the existing `EYENET_E2E=1` gate + testcontainers:

- Default suite stays SQLite in-memory. Fast, untouched.
- Postgres-pinned probes (advisory-lock serialization, COPY path, tsvector
  search, ON CONFLICT race): `_postgres` filename suffix +
  `monkeypatch.setenv("EYENET_STORAGE_TYPE", "postgres")`, mirroring the
  `_sqlite` suffix convention (CLAUDE.md §2.3 Rule 2). Gate behind `EYENET_E2E=1`.
- A cross-backend parity test (same ops, both backends, assert equal results)
  catches dialect drift. One file, parametrized over backend.

---

## 5. High-ingest ops (the ceilings SQLite never made you think about)

### 5.1 Connection exhaustion — MANDATORY at scale

Supervisor spawns N collector processes; each opens an asyncpg pool. Postgres
`max_connections` defaults to ~100. `20 collectors × pool 10 = 200` → refused
connections → ingest stalls. Fix:

- **pgbouncer in transaction-pooling mode** in front of Postgres.
- Small per-process SQLAlchemy pools (`pool_size=2-5`, modest `max_overflow`).
- Transaction mode means NO session-level state across statements — advisory
  locks must be `_xact_` (transaction-scoped, §2.3), which they already are.
  Prepared-statement caching must be disabled for asyncpg under pgbouncer
  (`statement_cache_size=0`) or you get cache-collision errors.

### 5.2 COPY for the firehose — see §2.6.

### 5.3 tsvector GIN write amplification

GIN maintenance costs on every message insert. Fine at first. If ingest write
latency climbs, options: `fastupdate=on` (default, batches GIN updates), or move
search indexing off the hot path. Knob to know exists, not a day-one fix.

---

## 6. Two-tree maintenance policy (keeping the tax survivable)

- SQLite is the default; Postgres is prod scale-out. They are NOT co-equal.
- A schema change goes into the tree of the backend that deployment runs. You do
  not lockstep both trees for a change a given deployment never sees.
- The cross-backend parity test (§4) is the tripwire for accidental divergence.
- Keep `SQLModel.metadata` the single schema source. Both baselines express the
  SAME logical schema; only the DDL dialect differs. Never let the two trees
  drift in table/column SHAPE, only in dialect expression.

---

## 7. The one-shot live data move (SQLite → Postgres)

The factory already IS the migration tool. Both backends go through the same
`SQLModel.metadata`, so the copy is generic and needs no column hand-mapping.

### 7.1 Safety rules (non-negotiable, from prior scars)

- **Never operate the live WAL DB in place.** `VACUUM INTO` a clean snapshot
  from the prod volume; migrate FROM the snapshot; leave the running DB alone
  until Postgres is verified clean. (We truncated a DB once already. Not twice.)
- The live volume is `docker_eyenet-data` (compose-prefixed), NOT `eyenet-data`.
  Use `docker exec` on the compose container or the prefixed volume name.
- Verify row counts AND the audit/file-access chain tip hash after the copy
  before cutting traffic over. Hashes are content-derived and order-preserved,
  so a correctly ordered copy keeps the chain valid end to end.

### 7.2 The script (sketch — ~60-100 lines, put in `dataset/` or `scripts/`)

```python
# ponytail: one-shot copy, both backends via the abstraction we already built.
# Run OFFLINE (ingest stopped) against a VACUUM INTO snapshot, not the live DB.
import asyncio, os
from pathlib import Path
from sqlmodel import SQLModel, select
import eyenet.models  # noqa: F401 — registers every table on metadata
from eyenet.storage.factory import get_repository

# source: sqlite snapshot;  dest: fresh postgres with 0001 baseline applied
async def move(snapshot_dir: Path) -> None:
    os.environ["EYENET_STORAGE_TYPE"] = "sqlite"
    src = get_repository(data_dir=snapshot_dir)          # main + audit
    os.environ["EYENET_STORAGE_TYPE"] = "postgres"
    dst = get_repository(url=os.environ["EYENET_PG_URL"])  # empty, baseline-migrated

    # metadata.sorted_tables is FK-ordered → insert parents before children.
    # audit/file-access tables copied IN ROWID ORDER to preserve chain linkage.
    for table in SQLModel.metadata.sorted_tables:
        async with src.session() as s:  # or per-engine for audit tables
            rows = (await s.exec(select(table))).all()
        if not rows:
            continue
        async with dst.session() as d:
            await d.exec(table.insert(), [dict(r._mapping) for r in rows])
            await d.commit()

    # reset Postgres IDENTITY/SERIAL sequences past the max copied id per table,
    # or the next insert collides:  SELECT setval(pg_get_serial_sequence(...), max(id))
    await reset_sequences(dst)
    await verify_counts_and_chain_tips(src, dst)  # FAIL LOUD on mismatch

asyncio.run(move(Path("data_snapshot")))
```

Wrinkles, all small and known:

- **FTS index is not data.** Skip it. The tsvector generated column rebuilds
  itself on insert; the GIN index is built by the baseline.
- **`vector_signature`** IS data. Copy it like any table.
- **Audit + file-access rows** copy verbatim, IN ORDER. Do them on the audit
  engine, not the main session. Chain stays valid (content-derived hashes).
- **Sequences** MUST be reset after copy (the `setval` step). Easy to forget,
  loud when you do.
- Do the whole thing with ingest STOPPED, against the snapshot, then swap.

---

## 8. Phasing / effort

```
Phase A  factory branch + engines + asyncpg/psycopg deps      ~0.5 day
Phase B  set_cursors_bulk, _body_match/tsvector, COPY bulk     ~1-2 days
Phase C  audit + file-access advisory-lock chains (+ tests)    ~2 days
Phase D  postgres migrations tree + 0001 baseline              ~1 day
Phase E  testcontainers + cross-backend parity test            ~1-2 days
Phase F  pgbouncer + pool sizing + ops runbook                 ~0.5-1 day
Phase G  one-shot data-move script + dry-run on snapshot       ~1 day
```

Roughly a focused week in a worktree (CLAUDE.md §6: worktree branch, atomic
`--no-ff` merge when the full battery is green). Zero caller changes: the
abstraction is the whole payoff of the M9 cutover.

Hardest correctness work: Phases C (advisory-lock chain) and G (verify the
chain tip survives the move). Biggest wall-clock sink: Phase E (Postgres test
infra). Do NOT ship Phase G until B-F are green and the parity test passes.
