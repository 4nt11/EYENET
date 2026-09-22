# SPDX-License-Identifier: AGPL-3.0-or-later
"""SQLite engine factory + DDL bootstrap for the async repository.

Two physical files per deployment:

  - ``main.db``  — every operational table (cases, clearance, observations,
                    attachments, messages, actors, linkages, personas, graph,
                    syslog, profiles, vectors, ...).
  - ``audit.db`` — append-only hash-chained ``audit_log`` table; physically
                    isolated for tamper-evidence.

Both expose async engines (``sqlite+aiosqlite://``) for the request path and
sync engines for DDL (``SQLModel.metadata.create_all`` is sync-only). The
sync engines are short-lived: created at boot, used for ``create_all``,
disposed.

SQLite pragmas applied to async engines:
  - ``foreign_keys = ON``         (FK constraints actually enforce)
  - ``journal_mode = WAL``        (concurrent readers + a writer)
  - ``synchronous = NORMAL``      (durability/perf for forensic work)

The ``hamming64(a, b)`` UDF (popcount of bitwise XOR) is registered on every
fresh connection so :class:`VectorsMixin` can compute Hamming distance via SQL.
"""

from __future__ import annotations

import fcntl
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, create_engine

_MAIN_TABLES: frozenset[str] = frozenset(
    {
        # social / message graph
        "source",
        "source_domain",
        "group_candidate",
        "group_candidate_mention",
        "collector_group_membership",
        "message_observation",
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
        "collector",
        "infrastructure_artifact",
        "actor_artifact",
        "group_access_artifact",
        "system_user",
        # observations
        "observation",
        # M10 — uploaded documents (classifier)
        "document",
        # corpus cursors
        "corpus_cursor",
        # profiles / linkage / persona / feedback
        "profile",
        "linkage",
        "persona",
        "persona_membership",
        "feedback_pair",
        "linkage_verifier_result",
        # graph (typed relations)
        "graph_node",
        "graph_edge",
        # syslog
        "system_log",
        # §4.8 clearance grants
        "system_user_clearance_grant",
        # §4.10 case tables
        "case_v2",
        "case_member",
        "case_collaborator",
        # M9.A1 — auth tables
        "system_user_credential",
        "refresh_token",
        "jwt_denylist",
        "system_user_scope",
        # M9.A3 — MFA TOTP login challenge
        "mfa_challenge",
        # M9.A4 — personal access tokens
        "personal_access_token",
        # M9.G1 — write idempotency replay guard
        "idempotency_record",
        # M9.G2 — per-transition event logs (§11.5 SSE replay source)
        "linkage_event_log",
        "persona_event_log",
        "identity_event_log",
    }
)
_AUDIT_TABLES: frozenset[str] = frozenset(
    {
        "audit_log",
        # M9.B1 — file-access crypto foundation (co-located in audit.db per §5.5)
        "system_user_signing_pubkey_history",
        "file_access_acknowledgment",
        # M9.B2 — hash-chained file-access journal (second chain in audit.db)
        "file_access_journal",
        # PHASE-4 — operator signing-key registration proof-of-possession
        # challenge (forensically relevant: it establishes who could sign).
        "signing_key_challenge",
    }
)

# ``vector_signature`` lives outside SQLModel.metadata — it's created via raw
# DDL below because there is no SQLModel table class for it.
_VECTOR_SIGNATURE_DDL = """
CREATE TABLE IF NOT EXISTS vector_signature (
    actor_id TEXT NOT NULL,
    primitive_name TEXT NOT NULL,
    simhash INTEGER NOT NULL,
    PRIMARY KEY (actor_id, primitive_name)
)
"""
_VECTOR_SIGNATURE_INDEX = (
    "CREATE INDEX IF NOT EXISTS ix_vs_primitive ON vector_signature(primitive_name)"
)

# M9.B1 — single-active-key enforcement (§5.7). A user must have AT MOST ONE
# row with ``retired_at IS NULL``. A partial (filtered) UNIQUE index makes a
# concurrent rotation race STRUCTURALLY impossible to leave two active keys:
# the second INSERT of an active row violates the index and rolls back.
# This is SQLite-dialect DDL (``WHERE`` on a UNIQUE index) so it lives in the
# backend layer — NOT the ANSI-clean model/mixin (CLAUDE.md §2.3 Rule 1).
# Future MySQL/Postgres backends express the same invariant their own way.
_SIGNING_PUBKEY_ACTIVE_UNIQUE_INDEX = (
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_signing_pubkey_active "
    "ON system_user_signing_pubkey_history(user_id) "
    "WHERE retired_at IS NULL"
)


def _hamming64(a: int | None, b: int | None) -> int:
    if a is None or b is None:
        return 0
    xor = (a ^ b) & 0xFFFF_FFFF_FFFF_FFFF
    return bin(xor).count("1")


def _wire_async_pragmas(engine: AsyncEngine) -> None:
    """Apply EYENET pragmas + register hamming64 UDF on every new connection."""

    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_conn: Any, _record: Any) -> None:
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys = ON")
        cur.execute("PRAGMA journal_mode = WAL")
        cur.execute("PRAGMA synchronous = NORMAL")
        cur.close()
        dbapi_conn.create_function("hamming64", 2, _hamming64, deterministic=True)


def _wire_sync_pragmas(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn: Any, _record: Any) -> None:
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys = ON")
        cur.execute("PRAGMA journal_mode = WAL")
        cur.execute("PRAGMA synchronous = NORMAL")
        cur.close()


def get_async_engine(db_path: Path) -> AsyncEngine:
    """Open an ``sqlite+aiosqlite://`` engine with WAL + pragmas + UDF."""

    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        future=True,
    )
    _wire_async_pragmas(engine)
    return engine


def get_sync_engine(db_path: Path) -> Engine:
    """Open a sync ``sqlite://`` engine for DDL only.

    ``SQLModel.metadata.create_all`` is sync-only. Use this engine at boot,
    then dispose it. The async engine handles every request-path query.
    """

    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{db_path}")
    _wire_sync_pragmas(engine)
    return engine


def open_in_memory_async_engine(name: str) -> AsyncEngine:
    """In-memory async engine, sharable via named cache.

    Two engines (async + sync) constructed with the same ``name`` see the
    same in-memory database via SQLite's ``cache=shared`` URI mode. This
    lets the sync DDL engine and the async query engine share schema and
    rows. ``StaticPool`` keeps the underlying connection alive for the
    engine's lifetime so the named DB isn't garbage-collected.
    """

    url = f"sqlite+aiosqlite:///file:{name}?mode=memory&cache=shared&uri=true"
    engine = create_async_engine(
        url,
        connect_args={"uri": True, "check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_conn: Any, _record: Any) -> None:
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys = OFF")
        cur.execute("PRAGMA journal_mode = WAL")
        cur.execute("PRAGMA synchronous = NORMAL")
        cur.close()
        dbapi_conn.create_function("hamming64", 2, _hamming64, deterministic=True)

    return engine


def open_in_memory_sync_engine(name: str) -> Engine:
    """In-memory sync engine sharing a named cache with its async sibling."""

    url = f"sqlite:///file:{name}?mode=memory&cache=shared&uri=true"
    engine = create_engine(
        url,
        connect_args={"uri": True, "check_same_thread": False},
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
def init_lock(data_dir: Path) -> Iterator[None]:
    """Hold an exclusive POSIX file lock during first-time schema init.

    Two ``eyenet`` processes booting against the same empty ``data_dir``
    would race in ``create_all(checkfirst=True)``. A blocking ``flock``
    forces the second to wait.
    """

    data_dir.mkdir(parents=True, exist_ok=True)
    lock_path = data_dir / ".eyenet-init.lock"
    with lock_path.open("w") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _filtered_tables(table_names: frozenset[str]) -> list[Any]:
    return [SQLModel.metadata.tables[n] for n in table_names if n in SQLModel.metadata.tables]


def init_main_db(sync_engine: Engine) -> None:
    """Create every MAIN table + the vector_signature side-table (sync)."""

    from sqlalchemy import text  # noqa: PLC0415

    import eyenet.models  # noqa: F401, PLC0415 — registers tables on SQLModel.metadata

    tables = _filtered_tables(_MAIN_TABLES)
    if tables:
        SQLModel.metadata.create_all(sync_engine, tables=tables)
    with sync_engine.begin() as conn:
        conn.execute(text(_VECTOR_SIGNATURE_DDL))
        conn.execute(text(_VECTOR_SIGNATURE_INDEX))


def init_audit_db(sync_engine: Engine) -> None:
    """Create the audit-log table on the audit DB (sync)."""

    from sqlalchemy import text  # noqa: PLC0415

    import eyenet.models  # noqa: F401, PLC0415

    tables = _filtered_tables(_AUDIT_TABLES)
    if tables:
        SQLModel.metadata.create_all(sync_engine, tables=tables)
    with sync_engine.begin() as conn:
        conn.execute(text(_SIGNING_PUBKEY_ACTIVE_UNIQUE_INDEX))


async def init_main_db_async(engine: AsyncEngine) -> None:
    """Create MAIN tables + vector_signature on an AsyncEngine.

    Required for in-memory engines, where sync and async create_engine
    calls produce separate ``:memory:`` databases that cannot share DDL.
    """

    from sqlalchemy import text  # noqa: PLC0415

    import eyenet.models  # noqa: F401, PLC0415

    tables = _filtered_tables(_MAIN_TABLES)
    async with engine.begin() as conn:
        if tables:
            await conn.run_sync(
                lambda sync_conn: SQLModel.metadata.create_all(sync_conn, tables=tables)
            )
        await conn.execute(text(_VECTOR_SIGNATURE_DDL))
        await conn.execute(text(_VECTOR_SIGNATURE_INDEX))


async def init_audit_db_async(engine: AsyncEngine) -> None:
    """Create audit_log on an AsyncEngine."""

    from sqlalchemy import text  # noqa: PLC0415

    import eyenet.models  # noqa: F401, PLC0415

    tables = _filtered_tables(_AUDIT_TABLES)
    async with engine.begin() as conn:
        if tables:
            await conn.run_sync(
                lambda sync_conn: SQLModel.metadata.create_all(sync_conn, tables=tables)
            )
        await conn.execute(text(_SIGNING_PUBKEY_ACTIVE_UNIQUE_INDEX))


__all__ = [
    "get_async_engine",
    "get_sync_engine",
    "init_audit_db",
    "init_lock",
    "init_main_db",
    "open_in_memory_async_engine",
    "open_in_memory_sync_engine",
]
