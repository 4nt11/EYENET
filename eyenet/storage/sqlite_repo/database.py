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
        "content_template",
        "attachment",
        "reaction",
        "actor_alias_history",
        "actor_relation",
        "manual_crew",
        "manual_crew_member",
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
        # incident detection — per-message multi-label classification results
        "incident",
        # operator-defined incident detection rules
        "incident_rule",
        # operator ground-truth label corrections (retraining signal)
        "incident_label",
        # victim-country attribution for incident-flagged messages (geo sidecar)
        "message_geo",
        # per-forum-thread rollup anchored on the OP (date + victim country)
        "thread_summary",
        # operator-queued forum reply-to-unlock requests
        "forum_reply_request",
        # category -> thread edge for the forum reader navigation
        "forum_thread_link",
        # operator-queued deep backfill of one forum thread
        "forum_backfill_request",
        # per-category backfill page cursor (resume, don't re-scrape from page 1)
        "forum_crawl_cursor",
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
        # §5.9 external-witness anchors
        "audit_anchor",
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

# Full-text search over message bodies — the incident triage ``?q=`` feed. FTS5 is a
# SQLite extension (dialect-specific → backend layer, CLAUDE.md §2.3 Rule 1); the mixin
# keeps a generic LIKE fallback and a future Postgres backend uses tsvector/GIN. The
# external-content table mirrors ``message.body`` by rowid (no duplicated storage); the
# three triggers keep the index in sync (bodies ARE edited — e.g. Matrix edits — so an
# UPDATE trigger is required, not just INSERT/DELETE).
_MESSAGE_FTS_DDL: tuple[str, ...] = (
    "CREATE VIRTUAL TABLE IF NOT EXISTS message_fts "
    "USING fts5(body, content='message', content_rowid='rowid')",
    "CREATE TRIGGER IF NOT EXISTS message_fts_ai AFTER INSERT ON message BEGIN "
    "INSERT INTO message_fts(rowid, body) VALUES (new.rowid, new.body); END",
    "CREATE TRIGGER IF NOT EXISTS message_fts_ad AFTER DELETE ON message BEGIN "
    "INSERT INTO message_fts(message_fts, rowid, body) VALUES('delete', old.rowid, old.body); "
    "END",
    "CREATE TRIGGER IF NOT EXISTS message_fts_au AFTER UPDATE ON message BEGIN "
    "INSERT INTO message_fts(message_fts, rowid, body) VALUES('delete', old.rowid, old.body); "
    "INSERT INTO message_fts(rowid, body) VALUES (new.rowid, new.body); END",
)
# 'rebuild' backfills rows that existed BEFORE the index (additive upgrade on a populated
# DB — create_all adds new tables without a wipe); triggers maintain it thereafter. A
# fresh (wipe-workflow) DB is empty here, so this is a no-op. Idempotent.
# ponytail: unconditional rebuild is O(corpus) each boot on SQLite; external-content FTS5
# has no cheap "is the index empty" probe (count() reports the CONTENT table). Fine at
# small-operator scale; the fleet-scale prod path is the Postgres tsvector override, not
# this. Gate it (e.g. a sentinel row) only if SQLite boot time ever bites.
_MESSAGE_FTS_REBUILD = "INSERT INTO message_fts(message_fts) VALUES('rebuild')"


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
        # Multi-process writer contention (both collectors + engine/sensor/linker/
        # verifier/graph + api all write main.db): without this a blocked writer gets
        # SQLITE_BUSY immediately ("database is locked") and, e.g., aborts a forum
        # category sweep. Wait up to 30s for the lock instead. Small-operator scale;
        # the real multi-writer answer is the Postgres backend, not a bigger timeout.
        cur.execute("PRAGMA busy_timeout = 30000")
        cur.close()
        dbapi_conn.create_function("hamming64", 2, _hamming64, deterministic=True)


def _wire_sync_pragmas(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn: Any, _record: Any) -> None:
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys = ON")
        cur.execute("PRAGMA journal_mode = WAL")
        cur.execute("PRAGMA synchronous = NORMAL")
        # Multi-process writer contention (both collectors + engine/sensor/linker/
        # verifier/graph + api all write main.db): without this a blocked writer gets
        # SQLITE_BUSY immediately ("database is locked") and, e.g., aborts a forum
        # category sweep. Wait up to 30s for the lock instead. Small-operator scale;
        # the real multi-writer answer is the Postgres backend, not a bigger timeout.
        cur.execute("PRAGMA busy_timeout = 30000")
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
        # Multi-process writer contention (both collectors + engine/sensor/linker/
        # verifier/graph + api all write main.db): without this a blocked writer gets
        # SQLITE_BUSY immediately ("database is locked") and, e.g., aborts a forum
        # category sweep. Wait up to 30s for the lock instead. Small-operator scale;
        # the real multi-writer answer is the Postgres backend, not a bigger timeout.
        cur.execute("PRAGMA busy_timeout = 30000")
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
        # Multi-process writer contention (both collectors + engine/sensor/linker/
        # verifier/graph + api all write main.db): without this a blocked writer gets
        # SQLITE_BUSY immediately ("database is locked") and, e.g., aborts a forum
        # category sweep. Wait up to 30s for the lock instead. Small-operator scale;
        # the real multi-writer answer is the Postgres backend, not a bigger timeout.
        cur.execute("PRAGMA busy_timeout = 30000")
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


# --- schema application: the SINGLE source of truth for the DDL --------------
# These build the physical schema on a sync Connection. The Alembic baseline
# revision (eyenet/storage/sqlite_repo/migrations/versions/) is the ONLY caller
# of the ``_apply_*``/``_drop_*`` pair — the app never calls create_all directly
# any more; it runs ``upgrade_to_head`` (migration history is authoritative).


def _apply_main_schema(conn: Any, table_names: frozenset[str]) -> None:
    """Create the given MAIN tables + vector_signature side-table + FTS index.

    ``table_names`` is passed by the caller (a migration revision) so the set is
    FROZEN in that revision, not tracked from the live ``_MAIN_TABLES`` — a new
    table added to the models gets its OWN revision, it does not retroactively
    grow an earlier baseline.
    """

    from sqlalchemy import text  # noqa: PLC0415

    import eyenet.models  # noqa: F401, PLC0415 — registers tables on SQLModel.metadata

    tables = _filtered_tables(table_names)
    if tables:
        SQLModel.metadata.create_all(conn, tables=tables)
    conn.execute(text(_VECTOR_SIGNATURE_DDL))
    conn.execute(text(_VECTOR_SIGNATURE_INDEX))
    for stmt in _MESSAGE_FTS_DDL:
        conn.execute(text(stmt))
    conn.execute(text(_MESSAGE_FTS_REBUILD))


def _apply_audit_schema(conn: Any, table_names: frozenset[str]) -> None:
    """Create the given audit tables + single-active-key partial UNIQUE index."""

    from sqlalchemy import text  # noqa: PLC0415

    import eyenet.models  # noqa: F401, PLC0415

    tables = _filtered_tables(table_names)
    if tables:
        SQLModel.metadata.create_all(conn, tables=tables)
    conn.execute(text(_SIGNING_PUBKEY_ACTIVE_UNIQUE_INDEX))


def _drop_main_schema(conn: Any, table_names: frozenset[str]) -> None:
    """Reverse :func:`_apply_main_schema` — the baseline's ``downgrade_main``."""

    from sqlalchemy import text  # noqa: PLC0415

    import eyenet.models  # noqa: F401, PLC0415

    for trig in ("message_fts_au", "message_fts_ad", "message_fts_ai"):
        conn.execute(text(f"DROP TRIGGER IF EXISTS {trig}"))
    conn.execute(text("DROP TABLE IF EXISTS message_fts"))
    conn.execute(text("DROP INDEX IF EXISTS ix_vs_primitive"))
    conn.execute(text("DROP TABLE IF EXISTS vector_signature"))
    tables = _filtered_tables(table_names)
    if tables:
        SQLModel.metadata.drop_all(conn, tables=tables)


def _drop_audit_schema(conn: Any, table_names: frozenset[str]) -> None:
    """Reverse :func:`_apply_audit_schema` — the baseline's ``downgrade_audit``."""

    from sqlalchemy import text  # noqa: PLC0415

    import eyenet.models  # noqa: F401, PLC0415

    conn.execute(text("DROP INDEX IF EXISTS uq_signing_pubkey_active"))
    tables = _filtered_tables(table_names)
    if tables:
        SQLModel.metadata.drop_all(conn, tables=tables)


# Objects that live OUTSIDE SQLModel.metadata (raw DDL). ``env.py`` excludes
# these from autogenerate so a future ``--autogenerate`` never emits a DROP for
# what it cannot see in the models (the FTS index, its shadow tables, the
# vector_signature side-table, and the partial UNIQUE index).
_RAW_DDL_OBJECTS: frozenset[str] = frozenset(
    {
        "vector_signature",
        "ix_vs_primitive",
        "message_fts",
        "message_fts_data",
        "message_fts_idx",
        "message_fts_docsize",
        "message_fts_config",
        "uq_signing_pubkey_active",
    }
)


def _sqlite_compare_type(
    context: Any,  # noqa: ARG001 — Alembic's fixed compare_type callback signature
    inspected_column: Any,  # noqa: ARG001
    metadata_column: Any,  # noqa: ARG001
    inspected_type: Any,
    metadata_type: Any,
) -> bool | None:
    """Alembic type comparator for SQLite: ignore string length-only diffs.

    SQLite does NOT enforce ``VARCHAR(n)`` length (everything is TEXT affinity),
    so a string column that differs only in declared length is not a real schema
    change — e.g. a live ``VARCHAR(12)`` column vs a models-side ``Enum`` (which
    renders as ``VARCHAR(14)``). Treat any string-vs-string pair as equal;
    return None for everything else so Alembic's default catches real type
    changes (``VARCHAR`` -> ``INTEGER`` etc.). CHECK/constraint changes are
    compared separately and are unaffected.
    """

    from sqlalchemy import String  # noqa: PLC0415

    if isinstance(inspected_type, String) and isinstance(metadata_type, String):
        return False
    return None


_MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def upgrade_to_head(main_engine: Engine, audit_engine: Engine) -> None:
    """Apply all pending Alembic migrations to both DBs — the boot DDL path.

    Replaces the legacy ``create_all`` bootstrap: migration history is the
    single source of truth. A fresh DB runs the baseline; an existing DB runs
    only what it is missing. Both engines are handed to ``env.py`` through
    ``config.attributes`` so in-memory (shared-cache ``StaticPool``) and
    file-backed engines migrate identically — no ``sqlalchemy.url`` juggling.
    """

    from alembic import command  # noqa: PLC0415
    from alembic.config import Config  # noqa: PLC0415

    cfg = Config()
    cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
    cfg.attributes["engines"] = {"main": main_engine, "audit": audit_engine}
    command.upgrade(cfg, "head")


__all__ = [
    "get_async_engine",
    "get_sync_engine",
    "init_lock",
    "open_in_memory_async_engine",
    "open_in_memory_sync_engine",
    "upgrade_to_head",
]
