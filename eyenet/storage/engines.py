"""Storage engine factory — backend-agnostic dispatch + per-store engines.

Two physical databases per EYENET deployment:

  - ``main``   — every operational table (cases, clearance grants, observations,
                  attachments, messages, actors, linkages, personas, graph, syslog,
                  profiles, corpus cursors, system users, ...). Cross-store SQL joins
                  are FIRST-CLASS here — the previous PLAN §5.2 "no cross-store joins"
                  rule has been relaxed (see updated §5.2). Atomic multi-row writes
                  span any operational table in one transaction.

  - ``audit``  — hash-chained, append-only forensic evidence: `audit_log` today, plus
                  `file_access_journal`, `file_access_acknowledgment`,
                  `system_user_signing_pubkey_history` once M9.1c lands. These tables
                  stay physically isolated from `main` so the forensic record
                  remains tamper-evident even if the operational DB is compromised.
                  Crossings INTO `audit` are application-layer (writes only — the
                  audit DB is not a read source for normal queries; you write to it
                  and read it independently for verification).

Backend selection is controlled by the ``EYENET_STORAGE_TYPE`` environment
variable (default ``sqlite``). The Store ABCs in ``contracts/storage.py`` are
backend-agnostic; concrete impls (``SQLiteAuditStore`` etc.) bind to a single
SQLAlchemy ``Engine`` and use SQLModel/SQLAlchemy Core for portability. Adding
a new backend = (a) register a builder in ``_BACKEND_BUILDERS`` here, (b)
implement new concrete ``X<Store>`` classes if any SQL is dialect-specific.

SQLite pragmas applied:
  - foreign_keys = ON          (so FK constraints actually enforce)
  - journal_mode = WAL         (concurrent readers + a writer)
  - synchronous = NORMAL       (durability/perf tradeoff for forensic work)
"""

from __future__ import annotations

import fcntl
import os
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from enum import StrEnum
from pathlib import Path
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, create_engine


class StoreName(StrEnum):
    """Logical database namespace.

    Two members reflect the M9.1a.2a physical split: ``MAIN`` for all
    operational tables (cross-joins enabled), ``AUDIT`` for the isolated
    append-only forensic evidence boundary. The pre-M9.1a 8-member layout
    (MESSAGES/CORPUS/OBSERVATIONS/PROFILES/VECTORS/GRAPH/SYSLOG/AUDIT)
    collapsed into these two — the rationale is documented in API_PLAN §5.2.
    """

    MAIN = "main"
    AUDIT = "audit"


# Per-store table assignment. Audit-DB contains ONLY append-only hash-chained
# evidence; everything else lives in MAIN. M9.1c will extend AUDIT with
# file_access_journal, file_access_acknowledgment, system_user_signing_pubkey_history.
_STORE_TABLES: dict[StoreName, frozenset[str]] = {
    StoreName.MAIN: frozenset(
        {
            # social / message graph
            "source",
            "actor",
            "group_",
            "message",
            "attachment",
            "reaction",
            "actor_alias_history",
            "membership",
            "group_snapshot",
            "identity",
            "identity_label",
            "engagement_authorization",
            "infrastructure_artifact",
            "actor_artifact",
            "system_user",
            # observations
            "observation",
            # corpus cursors
            "corpus_cursor",
            # profiles / linkage / persona / feedback
            "profile",
            "linkage",
            "persona",
            "persona_membership",
            "feedback_pair",
            # graph (typed relations)
            "graph_node",
            "graph_edge",
            # syslog
            "system_log",
            # §4.8 clearance grants — mutable, lifecycle-driven (NOT audit-tier)
            "system_user_clearance_grant",
            # §4.10 case tables — mutable forensic primitives (NOT audit-tier)
            "case_v2",
            "case_member",
            "case_collaborator",
        }
    ),
    StoreName.AUDIT: frozenset({"audit_log"}),
}


def store_tables(store: StoreName) -> frozenset[str]:
    return _STORE_TABLES[store]


def create_all_for(store: StoreName, engine: Engine) -> None:
    """``SQLModel.metadata.create_all`` filtered to the tables this store owns."""

    table_names = _STORE_TABLES[store]
    if not table_names:
        return
    tables = [
        SQLModel.metadata.tables[name] for name in table_names if name in SQLModel.metadata.tables
    ]
    SQLModel.metadata.create_all(engine, tables=tables)


# ---------------------------------------------------------------------------
# SQLite backend
# ---------------------------------------------------------------------------


def _wire_pragmas(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn: Any, _record: Any) -> None:
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys = ON")
        cur.execute("PRAGMA journal_mode = WAL")
        cur.execute("PRAGMA synchronous = NORMAL")
        cur.close()


def open_engine(path: Path, *, echo: bool = False) -> Engine:
    """Open a single SQLite engine at `path` with EYENET pragmas."""

    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{path}", echo=echo)
    _wire_pragmas(engine)
    return engine


def open_in_memory_engine() -> Engine:
    """Engine for unit tests. Same pragmas, in-memory.

    Uses StaticPool so all sessions/connections share the same in-memory
    database (`:memory:` gives each new connection a fresh empty database
    without this).

    FK constraints are disabled: in-memory tests focus on application-layer
    correctness, not DB referential integrity; integration tests run against
    real files with FK enforcement on.
    """

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn: Any, _record: Any) -> None:
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys = OFF")
        cur.execute("PRAGMA journal_mode = WAL")
        cur.execute("PRAGMA synchronous = NORMAL")
        cur.close()

    return engine


@contextmanager
def _init_lock(data_dir: Path) -> Iterator[None]:
    """Hold an exclusive POSIX file lock during first-time schema init.

    Two `eyenet` processes booting against the same empty `data_dir` would
    otherwise race in SQLAlchemy's `create_all(checkfirst=True)` — both see
    a missing table, both emit `CREATE TABLE`, the second loses. A blocking
    `flock(LOCK_EX)` makes the second wait until the first commits; then
    `checkfirst` no-ops every table.
    """

    data_dir.mkdir(parents=True, exist_ok=True)
    lock_path = data_dir / ".eyenet-init.lock"
    with lock_path.open("w") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _sqlite_open_all(data_dir: Path) -> dict[StoreName, Engine]:
    """SQLite backend: one `.db` file per StoreName under ``data_dir/``."""

    engines: dict[StoreName, Engine] = {}
    with _init_lock(data_dir):
        for store in StoreName:
            engine = open_engine(data_dir / f"{store.value}.db")
            create_all_for(store, engine)
            engines[store] = engine
    return engines


# ---------------------------------------------------------------------------
# Backend dispatch
# ---------------------------------------------------------------------------

_BACKEND_BUILDERS: dict[str, Callable[[Path], dict[StoreName, Engine]]] = {
    "sqlite": _sqlite_open_all,
    # Future: "mysql": _mysql_open_all, "mariadb": _mariadb_open_all,
    # "postgres": _postgres_open_all. Each builder receives the data_dir
    # (used by SQLite for file paths; ignored by network-backed engines,
    # which read DSN bits from environment variables instead).
}

_BACKEND_ENV = "EYENET_STORAGE_TYPE"
_DEFAULT_BACKEND = "sqlite"


def _selected_backend() -> str:
    """Backend name from ``EYENET_STORAGE_TYPE`` (default ``sqlite``)."""

    return os.environ.get(_BACKEND_ENV, _DEFAULT_BACKEND).strip().lower()


def make_engines(data_dir: Path) -> dict[StoreName, Engine]:
    """Open every StoreName's engine for the configured backend.

    Backend is selected by the ``EYENET_STORAGE_TYPE`` env var (default
    ``sqlite``). Unknown backends raise ``NotImplementedError`` with a
    forward-looking message listing the supported set.
    """

    backend = _selected_backend()
    builder = _BACKEND_BUILDERS.get(backend)
    if builder is None:
        supported = sorted(_BACKEND_BUILDERS)
        raise NotImplementedError(
            f"storage backend {backend!r} not yet implemented; supported: {supported}. "
            "Set EYENET_STORAGE_TYPE to a supported backend or add a builder to "
            "_BACKEND_BUILDERS in eyenet/storage/engines.py."
        )
    return builder(data_dir)


def open_all(data_dir: Path) -> dict[StoreName, Engine]:
    """Backwards-compatible alias for ``make_engines``.

    Pre-M9.1a.2a callers wrote ``open_all(data_dir)``. New code should use
    ``make_engines`` to signal that the engine factory dispatches on
    ``EYENET_STORAGE_TYPE``.
    """

    return make_engines(data_dir)


def close_all(engines: Iterable[Engine]) -> None:
    for e in engines:
        e.dispose()


__all__ = [
    "StoreName",
    "close_all",
    "create_all_for",
    "make_engines",
    "open_all",
    "open_engine",
    "open_in_memory_engine",
    "store_tables",
]
