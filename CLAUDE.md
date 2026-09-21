# CLAUDE.md — EYENET project guidance

This file is the project-level orientation for any Claude session working on
EYENET. It distills the architectural decisions, conventions, and traps that
showed up during the M9 storage cutover and earlier milestones. The global
`~/.claude/CLAUDE.md` persona/style rules still apply on top of this.

The auto-memory under `~/.claude/projects/-home-anti-Projects-EYENET/memory/` is
the day-to-day journal; this file is the durable codification of decisions
that survive across sessions and don't decay.

---

## 1. What EYENET is

Observation framework for forensic analysis of threat actors. Consumes
BEHAVE-TEXT primitives, sibling of DECNET. Targets **small operators** — the
"little guy" running a few collectors, not enterprise. Default cardinality
of services is `1`; the design scales out only where explicitly justified.

**Operator-grade evidence**, not privacy-minimized: retain full content,
audit every access, never hobble the operator. Bodies in `MessageTable`,
attachments on disk, signed file-access journal for sensitive evidence.

**Pre-public posture**: no Alembic, no migrations. Schema changes =
`rm data/*.db && eyenet init`. Alembic baseline lands at v0.1.0.

---

## 2. Storage layer — the DECNET abstract-factory pattern

EYENET's storage is the most architecturally significant subsystem.
Get this wrong and everything downstream is poisoned.

### 2.1 Three-layer composition

```
BaseRepository(ABC)                       ← eyenet/storage/repository.py
    ↑                                       (flat ~80-method async ABC)
SQLModelRepository(*mixins, BaseRepository)  ← eyenet/storage/sqlmodel_repo/
    ↑                                       (generic SQLModel/SQLAlchemy mixins —
SQLiteRepository(SQLModelRepository)        ANSI SQL only, no dialect leak)
                                          ← eyenet/storage/sqlite_repo/
                                            (concrete SQLite — overrides ~5 methods)
```

Future MySQL/Postgres backends are `MySQLRepository(SQLModelRepository)` and
`PostgresRepository(SQLModelRepository)` with their own ~5-method override
sets. They share the entire `sqlmodel_repo/` mixin layer.

### 2.2 Env-var dispatched factory

```python
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

# Reads EYENET_STORAGE_TYPE (default "sqlite"); forwards kwargs to the backend
storage: BaseRepository = get_repository(data_dir=Path("data/"))
storage_inmem: BaseRepository = get_repository(in_memory=True)
```

**Production code never imports a concrete backend directly.** Always
`get_repository(...)` + type-hint as `BaseRepository`. The factory is the
single dispatch point; adding a backend means adding one branch in
`factory.py`, not editing every caller.

### 2.3 Two firm rules — these have bitten me twice already

**Rule 1 — No dialect leak in mixins.**
The `sqlmodel_repo/` layer uses only generic SQLModel ORM (SELECT-then-add,
SELECT-then-update). Dialect-specific SQL belongs in the concrete backend:

- `sqlalchemy.dialects.sqlite.insert` + `ON CONFLICT DO UPDATE` →
  `sqlite_repo/repository.py`
- `BEGIN IMMEDIATE` on raw aiosqlite cursor → `sqlite_repo/repository.py`
- (Future) `INSERT IGNORE`, `INFORMATION_SCHEMA`, `SERIALIZABLE` → respective
  backend's `repository.py`

**Override pattern.** Declare on `SQLModelRepository` with
`raise NotImplementedError`; override on the concrete subclass. The audit
`_append_audit_locked` and SQLite `set_cursors_bulk` upsert are the
established examples. If you find yourself importing
`from sqlalchemy.dialects.<X>` into a mixin, stop and move the method.

**Rule 2 — Tests use `BaseRepository` + `get_repository()`, never direct
backend imports.**
Every test types against the abstract surface and constructs via the factory.
The ONE exception is SQLite-impl-specific probes (audit `BEGIN IMMEDIATE`,
init lock, pragmas, dialect upsert behavior) — these pin via
`monkeypatch.setenv("EYENET_STORAGE_TYPE", "sqlite")` AND get a `_sqlite`
filename suffix so future MySQL/Postgres mirrors sit alongside without
collision.

```python
# Default fixture (most tests):
@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)

# SQLite-pinned fixture (impl probe, filename: test_*_sqlite.py):
@pytest.fixture
def storage(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> BaseRepository:
    monkeypatch.setenv("EYENET_STORAGE_TYPE", "sqlite")
    return get_repository(data_dir=tmp_path)
```

Module-private helpers in the mixin layer (e.g. `_hex_to_int` in
`sqlmodel_repo/vectors.py`) are imported from the mixin module — that's not
a backend leak, the mixin is the shared layer.

### 2.4 Flat naming, no sub-stores

Every method on the repository is dotless: `storage.create_case(...)`, not
`storage.cases.create_case(...)`. The legacy sub-store accessor pattern
(`storage.X.method`) is **gone**. Naming convention: `<verb>_<domain>`
(`append_audit`, `put_observation`, `transition_linkage`,
`merge_actors_into_persona`, `graph_stats`, `upsert_graph_node`).
See `development/API_PLAN.md §M9.1a.5` for the full naming map.

### 2.5 Async by default; sync only at boot

Every repo method is `async def`. Engines use `sqlite+aiosqlite://` +
`sqlmodel.ext.asyncio.session.AsyncSession`. The legacy sync `Session(engine)`
path is gone.

DDL is sync because `SQLModel.metadata.create_all` is sync-only. A parallel
`get_sync_engine` is opened at boot for DDL and disposed after init.

**Use `from sqlmodel.ext.asyncio.session import AsyncSession`** — it has
`.exec()`. `sqlalchemy.ext.asyncio.AsyncSession` does NOT have `.exec()` —
mixing them is a classic trap.

### 2.6 Audit chain — single-writer invariant

The audit log is hash-chained and tamper-evident. Writes go through
`_append_audit_locked` on the concrete backend. SQLite implementation:

- In-process: `asyncio.Lock` serializes coroutines on the same connection
- Cross-process: `BEGIN IMMEDIATE` on a raw aiosqlite cursor acquires
  SQLite's RESERVED lock so concurrent processes serialize at the file
- The hash chain: read last `self_hash`, compute new `self_hash` over the
  envelope + `prev_hash`, INSERT, COMMIT — all inside the `BEGIN IMMEDIATE`
  transaction.

Audit lives in a separate physical file (`audit.db`) from main data
(`main.db`). Two engines, two session factories. This is a SQLite-deployment
choice for tamper-evidence isolation, not a model concern.

### 2.7 The `session()` escape hatch

`BaseRepository.session()` is an `async with` context manager yielding the
main-engine `AsyncSession`. Reserved for transactions that genuinely don't
fit a single repo method — Matrix edit patching (read target, mutate
`source_specific` JSON, write back) and reaction inserts (custom INSERT
with idempotency). Production uses it sparingly. If you reach for it, ask
whether the operation belongs as a new flat method first.

### 2.8 Bulk helpers — the async overhead reality

Per-call async session overhead is ~2-5ms higher than the legacy sync path
because SQLAlchemy + aiosqlite acquire/release a thread-bound proxy
connection on each call. Hot loops (the StylometricSensor dispatch, the
Verifier's window-corpus loader) hit this hard.

Mitigation: dedicated bulk helpers. **Add them to the mixin if they're
generic.** Existing examples:

- `get_cursors_bulk(actor_id, primitive_names)` — one SELECT for all cursors
- `put_observations_bulk(rows)` — one session for many inserts
- `set_cursors_bulk(actor_id, updates)` — one transaction; SQLite override
  uses `INSERT ... ON CONFLICT DO UPDATE` for race safety
- `recent_message_bodies_for_actor(actor_id, limit)` — replaces a
  `storage._engines[MAIN] + raw Session + LIFO select` pattern with one
  round-trip on the abstraction

Before adding one, check that the perf problem is real (measure under
realistic concurrency), not theoretical.

### 2.9 In-memory engines — shared cache trick

`SQLiteRepository(in_memory=True)` opens two named in-memory DBs:
`file:{name}?mode=memory&cache=shared&uri=true` with `StaticPool`. This
lets the sync DDL engine and the async query engine share the same SQLite
in-memory database. Without `cache=shared`, you get two isolated empty
DBs and the async queries fail because the tables don't exist.

Names are per-instance (`f"eyenet-main-{uuid.uuid4().hex}"`) so concurrent
tests don't share state.

---

## 3. Tests

### 3.1 Marker discipline

Every test has exactly one **speed marker**: `unit`, `integration`, or `e2e`.
The default `pytest` run selects `-m "unit or contract"`. Integration tests
need `-m "integration or unit or contract"`. E2E tests skip unless
`EYENET_E2E=1` (testcontainers/NATS) or `EYENET_E2E_JAEGER=1` (Jaeger).

### 3.2 Shared seed helper

`tests/_seed.py:seed_telegram_fixture(storage, records, now)` is the
canonical way to populate a synthetic source/group/actor/message graph in
integration tests. Don't re-implement the legacy
`engine + Session + upsert_*` block per file — call the helper.

### 3.3 Test ordering flakes vs real failures

`pytest-randomly` is enabled by default. If a test passes alone but fails
in the random-ordered run, it's almost certainly state-pollution from a
neighbor (env vars, structlog config, captured logs). Verify with
`pytest -p no:randomly` before pursuing a fix.

The three impostor-pool log-capture tests and the
`test_failure_isolation` throughput test are known offenders. Don't waste
budget chasing them as refactor regressions until you've reproduced under
`-p no:randomly`.

### 3.4 Coverage gate

`--cov-fail-under=84` in pyproject. Coverage is computed over `eyenet/`,
with `tests/`, `eyenet/cli/__main__.py`, and the live-service-only
collectors (`bus/nats.py`, `collectors/telegram/real.py`, `auth.py`,
`collectors/matrix/real.py`) omitted. A delta-no-drop guard
(`coverage_no_drop` in `.githooks/lib/coverage.sh`) refuses any decrease
from `.coverage-baseline`. Update the baseline only when intentional.

---

## 4. Production conventions

### 4.1 No `assert` in production code

`assert` is stripped under `python -O`. Use typed exceptions:

```python
# bad:
assert source_id is not None, "source missing"

# good:
if source_id is None:
    raise RuntimeError("source_uuid not set — on_subscribe incomplete")
```

`assert` is fine in tests (the per-file-ignore in pyproject allows `S101`).

### 4.2 No `try/except/pass`

Always log or re-raise. Only catch the exact expected exception. The
audit-emit code path uses `audit_or_warn` to log a syslog WARN on
cross-engine inconsistency, then re-raise. Don't broaden the catch.

### 4.3 No `Co-Authored-By Claude` trailer

Strip from existing local commits when found; never add to new ones.

### 4.4 Service abstraction

Every service inherits `ServiceBase`. Constructor signature:

```python
def __init__(self, *, bus: Bus, storage: BaseRepository) -> None:
```

`ServiceBase` provides `.bus`, `.storage`, `.publisher`, `.audit`,
`.syslog(...)`, `.shutdown()`, `.stop_event`. Subclasses implement
`name`, `instance_id`, `on_subscribe()`, optionally `tick()`.

The `audit` accessor lazy-builds an `AuditEmitter(publisher, storage,
service=name, instance_id=instance_id)`. AuditEmitter takes the FULL repo,
not a sub-store — calls `storage.append_audit(...)`.

### 4.5 Tracing propagation

Every bus subscriber calls `attach_from_headers(headers)` **inside the
`create_task` body**, not before scheduling. Scheduling-time attach is a
no-op because the task runs later in a fresh context. Preserve the
`_process(env)` test-monkeypatch signature.

### 4.6 Plural services from day one

Never design a 1..N service as a singleton-to-be-refactored. Collectors,
sensors, identities — all multi-instance from the first commit.

### 4.7 Per-source identity TOML fields use the source prefix

`matrix_monitor_rooms`, not `monitor_rooms`. Mirrors `telegram_api_id`,
`telegram_api_hash` grouping.

### 4.8 Matrix collector is always invisible

`set_presence="offline"` is hard-coded on every `nio` sync call. No
operator knob. See `[[feedback_matrix_collector_offline_only]]`.

---

## 5. Locale + language-agnostic primitives

EYENET ships locale-aware primitives, not Spanish-specific ones.
Output is BCP-47 `xx-YY`. Spanish is the first **calibrated** language,
not the scope. The M5 calibration grid + Rutify is the per-language
empirical tuning loop. When adding a primitive, design for the
locale-detection path first, then calibrate per language.

`spacy>=3.7,<4.0` is a CORE runtime dep (not optional). The
`es_core_news_sm` model (~13MB) auto-fetches on first run from
`eyenet/sensor/primitives/_locale_morph_kernel.py`. Operators accept the
storage cost in exchange for working software out of the box —
small-operator scope.

The Spanish `sm` lemmatizer cannot decompose diminutives, so the M6.5
trio uses surface-suffix matching instead. All four stylometric simhashes
are **disabled for Spanish** because the precision floor was unreached
during M5/M6.5 calibration. The Verifier is the Spanish-linkage plan.

---

## 6. Worktree-based atomic cutovers

For deep refactors (the M9.1a.5 storage cutover, future backend additions),
work in a git worktree on a dedicated branch. The cutover is committed as a
series inside the worktree (intermediate commits OK to be broken because
they're isolated), then merged to main as one `--no-ff` merge commit when
the full battery is green.

Pattern:
1. `EnterWorktree(name="phaseN-...")` — fresh branch from current HEAD
2. Land the work in incremental commits (the random-ordered suite must be
   green at the merge point, not at every intermediate commit)
3. Run the full pre-commit gate: ruff format + check, mypy --strict,
   bandit, detect-secrets, deptry, full pytest with `EYENET_E2E=1` if NATS
   is available
4. `ExitWorktree(action="keep")` — leave the branch on disk
5. From main: `git merge --no-ff <branch> -m "..."`
6. Cleanup via `git worktree remove .claude/worktrees/<name>` later

Use `pytest --timeout=60 -p no:randomly` for sweeps that have a history of
hanging — the global `--timeout=30` in pyproject covers per-test hangs but
some integration tests legitimately need more than that.

---

## 7. Memory system

`~/.claude/projects/-home-anti-Projects-EYENET/memory/` is the persistent
journal. Two memory rules saved during the storage cutover are
load-bearing for every future storage change:

- `feedback_no_dialect_leak_in_mixins` — Rule 1 above
- `feedback_use_basereo_abstraction_in_tests` — Rule 2 above

Plus the long-standing ones: small-operator scope, operator-grade evidence,
no-assert, no-try/except/pass, no-coauthor-trailer, plural-services-from-
day-one, identity-toml-source-prefix.

Update these only when the rule itself changes. Add new ones liberally
when a correction or non-obvious confirmation comes in.

---

## 8. Reading order for a new session

1. `PLAN.md` — milestone roadmap (M1..M8 done, M9 in progress)
2. `development/API_PLAN.md` — M9 HTTP API spec (the source of truth for v1 routes)
   - §M9.1a.5 specifically — the storage cutover this CLAUDE.md codifies
3. `development/MODELS.md` — table-by-table schema reference
4. `development/eyenet-erd.drawio` — visual ERD generated from MODELS.md; open in drawio
5. `eyenet/storage/repository.py` — the flat ABC; methods document themselves
6. `eyenet/storage/sqlmodel_repo/__init__.py` — mixin composition order
7. The active memory files in
   `~/.claude/projects/-home-anti-Projects-EYENET/memory/MEMORY.md`

---

## 9. When in doubt

- **Touching storage?** Re-read §2.3 (the two firm rules) before writing a
  single line.
- **Touching tests?** Default fixture is `get_repository(in_memory=True)`
  typed as `BaseRepository`. SQLite probes get `_sqlite` suffix + env pin.
- **Adding a new flat method?** Declare on `BaseRepository`, implement on
  the relevant mixin, ensure it has no dialect-specific SQL. If it does,
  declare + `raise NotImplementedError` on the mixin and override on the
  concrete backend.
- **Hitting async session overhead?** Check whether the operation can be
  batched (`*_bulk` helpers). Don't reach for `session()` first.
- **Deep refactor?** Worktree branch + atomic merge.
- **A test passes alone but fails in the suite?** Try `-p no:randomly`
  before pursuing it as a regression.
