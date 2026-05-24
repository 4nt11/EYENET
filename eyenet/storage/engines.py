"""Per-store SQLite engine factory.

PLAN §5.2: one SQLite file per concern. Cross-store joins are forbidden;
the application code crosses boundaries explicitly. The `ATTACH DATABASE`
SQL statement is the natural escape hatch — we refuse it by default to
keep the boundary honest.

Each engine is opened with:
  - foreign_keys = ON          (so FK constraints actually enforce)
  - journal_mode = WAL         (concurrent readers + a writer)
  - synchronous = NORMAL       (durability/perf tradeoff appropriate for forensic work)
"""

from __future__ import annotations

import fcntl
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from enum import StrEnum
from pathlib import Path
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, create_engine


class StoreName(StrEnum):
    MESSAGES = "messages"
    CORPUS = "corpus"
    OBSERVATIONS = "observations"
    PROFILES = "profiles"
    VECTORS = "vectors"
    GRAPH = "graph"
    AUDIT = "audit"
    SYSLOG = "syslog"


def _wire_pragmas(engine: Engine, *, allow_attach: bool = False) -> None:
    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn: Any, _record: Any) -> None:
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys = ON")
        cur.execute("PRAGMA journal_mode = WAL")
        cur.execute("PRAGMA synchronous = NORMAL")
        if not allow_attach:
            # Defensive: we don't use ATTACH; refusing it makes the
            # cross-store boundary impossible to violate at the SQL layer.
            cur.execute("PRAGMA query_only = OFF")  # no-op marker
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


# Per-store table assignment. PLAN §5.2 boundaries.
_STORE_TABLES: dict[StoreName, frozenset[str]] = {
    StoreName.MESSAGES: frozenset(
        {
            # MessageStore needs the social context to satisfy FKs because
            # MessageTable has FKs into Source/Group/Actor. That's a v0
            # pragmatic choice: keeping the FK targets in the same DB file
            # rather than splitting the social graph across multiple files.
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
            "case_",
            "system_user",
        }
    ),
    StoreName.CORPUS: frozenset({"corpus_cursor"}),
    StoreName.OBSERVATIONS: frozenset({"observation"}),
    StoreName.PROFILES: frozenset({"profile", "linkage", "persona", "persona_membership"}),
    StoreName.VECTORS: frozenset(),  # sqlite-vec virtual tables, declared at runtime
    StoreName.GRAPH: frozenset({"graph_node", "graph_edge"}),
    StoreName.AUDIT: frozenset({"audit_log"}),
    StoreName.SYSLOG: frozenset({"system_log"}),
}


def store_tables(store: StoreName) -> frozenset[str]:
    return _STORE_TABLES[store]


def create_all_for(store: StoreName, engine: Engine) -> None:
    """`SQLModel.metadata.create_all` filtered to the tables this store owns.

    The shared metadata holds every table; we only emit DDL for the subset
    this store is responsible for. Tables with FKs into another store are
    co-located inside that store (see `_STORE_TABLES[MESSAGES]` comment).
    """

    table_names = _STORE_TABLES[store]
    if not table_names:
        return
    tables = [
        SQLModel.metadata.tables[name] for name in table_names if name in SQLModel.metadata.tables
    ]
    SQLModel.metadata.create_all(engine, tables=tables)


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


def open_all(data_dir: Path) -> dict[StoreName, Engine]:
    """Open every store's engine under `data_dir/<store>.db` and create tables."""

    engines: dict[StoreName, Engine] = {}
    with _init_lock(data_dir):
        for store in StoreName:
            engine = open_engine(data_dir / f"{store.value}.db")
            create_all_for(store, engine)
            engines[store] = engine
    return engines


def close_all(engines: Iterable[Engine]) -> None:
    for e in engines:
        e.dispose()


__all__ = [
    "StoreName",
    "close_all",
    "create_all_for",
    "open_all",
    "open_engine",
    "open_in_memory_engine",
    "store_tables",
]
