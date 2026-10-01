# SPDX-License-Identifier: AGPL-3.0-or-later
"""PostgreSQL engine factory + DDL bootstrap for the async repository.

Two physical DATABASES per deployment (the Postgres analogue of SQLite's two
files), preserving the tamper-evidence isolation of the audit store:

  - main   — every operational table.
  - audit  — the append-only hash-chained ``audit_log`` + the file-access journal
             + signing-key tables. Conventionally ``<main>_audit``.

The operator provisions both databases (Postgres cannot ``CREATE DATABASE`` from
within a connection to another DB); this module only creates the SCHEMA inside
them via the Alembic baseline. asyncpg drives the request path; psycopg drives
the sync DDL/Alembic engine.

Raw DDL that lives OUTSIDE ``SQLModel.metadata`` (the ``hamming64`` distance UDF,
the ``vector_signature`` side-table, the partial UNIQUE index) is applied by the
baseline and excluded from autogenerate in ``env.py`` — the Postgres mirror of
the SQLite backend's raw-DDL set.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import URL, make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.util import await_only
from sqlmodel import SQLModel, create_engine

_ASYNC_DRIVER = "postgresql+asyncpg"
_SYNC_DRIVER = "postgresql+psycopg"

# --- raw DDL (outside SQLModel.metadata) -------------------------------------

# hamming64(a, b) — popcount(a XOR b) over 64-bit signed integers, byte-for-byte
# equivalent to the SQLite Python UDF (verified incl. negative/max values). The
# VectorsMixin issues ``hamming64(:q, simhash)`` unchanged; the backend supplies
# the function. bit_count takes bit/bytea (not bigint), hence the bit(64) cast.
_HAMMING64_FN = (
    "CREATE OR REPLACE FUNCTION hamming64(a bigint, b bigint) RETURNS integer "
    "LANGUAGE sql IMMUTABLE PARALLEL SAFE AS "
    "$$ SELECT bit_count((a::bit(64)) # (b::bit(64)))::int $$"
)
_HAMMING64_DROP = "DROP FUNCTION IF EXISTS hamming64(bigint, bigint)"

# vector_signature — no SQLModel table class; actor_id is TEXT because the mixin
# binds ``str(actor_id)`` (mirrors the SQLite side-table exactly). simhash is a
# signed 64-bit value (_hex_to_int yields int64), so BIGINT.
_VECTOR_SIGNATURE_DDL = (
    "CREATE TABLE IF NOT EXISTS vector_signature ("
    "actor_id TEXT NOT NULL, primitive_name TEXT NOT NULL, "
    "simhash BIGINT NOT NULL, PRIMARY KEY (actor_id, primitive_name))"
)
_VECTOR_SIGNATURE_INDEX = (
    "CREATE INDEX IF NOT EXISTS ix_vs_primitive ON vector_signature(primitive_name)"
)

# Single-active-key enforcement (§5.7) — native Postgres partial UNIQUE index,
# the same invariant the SQLite backend expresses with its own partial index.
_SIGNING_PUBKEY_ACTIVE_UNIQUE_INDEX = (
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_signing_pubkey_active "
    "ON system_user_signing_pubkey_history(user_id) WHERE retired_at IS NULL"
)

# Names excluded from autogenerate (env.py) so a future --autogenerate never
# proposes DROPs for schema it cannot see in the models.
_RAW_DDL_OBJECTS: frozenset[str] = frozenset(
    {"vector_signature", "ix_vs_primitive", "uq_signing_pubkey_active", "hamming64"}
)


# --- engine factories --------------------------------------------------------


def _async_url(url: str | URL) -> URL:
    return make_url(url).set(drivername=_ASYNC_DRIVER)


def _sync_url(url: str | URL) -> URL:
    return make_url(url).set(drivername=_SYNC_DRIVER)


def audit_url_for(url: str | URL) -> URL:
    """Derive the audit-DB URL from the main URL (``<db>_audit``)."""
    u = make_url(url)
    if not u.database:
        raise ValueError("Postgres URL must name a database to derive the audit DB")
    return u.set(database=f"{u.database}_audit")


def _register_timestamp_codec(dbapi_conn: Any, _record: Any) -> None:
    """Accept tz-aware datetimes for ``timestamp`` columns on asyncpg.

    EYENET timestamps are tz-aware UTC, but the schema uses ``TIMESTAMP WITHOUT
    TIME ZONE`` (the SQLite heritage — SQLite has no tz-aware type). asyncpg's
    built-in binary codec refuses a tz-aware datetime for that type. A text-mode
    codec strips the tz on encode (all values are UTC) and reattaches UTC on
    decode, so a value round-trips tz-aware UTC exactly as SQLite returns it.
    This matters for the hash chains: ``self_hash`` covers ``served_at``/``at``
    via ``isoformat()``, so a naive read-back (no ``+00:00``) would recompute a
    different hash and fail chain verification. Registered per-connection via the
    connect event; ``await_only`` runs the coroutine in the connection's greenlet.
    """
    raw = dbapi_conn.driver_connection  # asyncpg.Connection

    await_only(
        raw.set_type_codec(
            "timestamp",
            schema="pg_catalog",
            encoder=lambda dt: dt.replace(tzinfo=None).isoformat(sep=" "),
            decoder=lambda s: datetime.fromisoformat(s).replace(tzinfo=UTC),
            format="text",
        )
    )


def get_async_engine(url: str | URL, *, pool_size: int, max_overflow: int) -> AsyncEngine:
    """Open an ``postgresql+asyncpg://`` engine for the request path.

    ``statement_cache_size=0`` disables asyncpg's prepared-statement cache so the
    engine is safe behind pgbouncer in transaction-pooling mode (the intended
    high-ingest fronting; see POSTGRES_PORT.md §5.1). Harmless on a direct
    connection. Pools are kept SMALL per-process because many collector
    processes each hold one — the connection budget is the real ceiling.
    """
    engine = create_async_engine(
        _async_url(url),
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_pre_ping=True,
        connect_args={"statement_cache_size": 0},
        future=True,
    )
    event.listen(engine.sync_engine, "connect", _register_timestamp_codec)
    return engine


def get_sync_engine(url: str | URL) -> Engine:
    """Open a sync ``postgresql+psycopg://`` engine for DDL / Alembic only."""
    return create_engine(_sync_url(url), future=True)


# --- schema application (the single source of truth for the baseline DDL) ----


def _filtered_tables(table_names: frozenset[str]) -> list[Any]:
    return [SQLModel.metadata.tables[n] for n in table_names if n in SQLModel.metadata.tables]


def _apply_main_schema(conn: Any, table_names: frozenset[str]) -> None:
    """Create the given MAIN tables + the hamming64 UDF + vector_signature."""
    from sqlalchemy import text  # noqa: PLC0415

    import eyenet.models  # noqa: F401, PLC0415 — registers tables on metadata

    tables = _filtered_tables(table_names)
    if tables:
        SQLModel.metadata.create_all(conn, tables=tables)
    conn.execute(text(_HAMMING64_FN))
    conn.execute(text(_VECTOR_SIGNATURE_DDL))
    conn.execute(text(_VECTOR_SIGNATURE_INDEX))


def _apply_audit_schema(conn: Any, table_names: frozenset[str]) -> None:
    """Create the given audit tables + the single-active-key partial UNIQUE index."""
    from sqlalchemy import text  # noqa: PLC0415

    import eyenet.models  # noqa: F401, PLC0415

    tables = _filtered_tables(table_names)
    if tables:
        SQLModel.metadata.create_all(conn, tables=tables)
    conn.execute(text(_SIGNING_PUBKEY_ACTIVE_UNIQUE_INDEX))


def _drop_main_schema(conn: Any, table_names: frozenset[str]) -> None:
    from sqlalchemy import text  # noqa: PLC0415

    import eyenet.models  # noqa: F401, PLC0415

    conn.execute(text("DROP INDEX IF EXISTS ix_vs_primitive"))
    conn.execute(text("DROP TABLE IF EXISTS vector_signature"))
    conn.execute(text(_HAMMING64_DROP))
    tables = _filtered_tables(table_names)
    if tables:
        SQLModel.metadata.drop_all(conn, tables=tables)


def _drop_audit_schema(conn: Any, table_names: frozenset[str]) -> None:
    from sqlalchemy import text  # noqa: PLC0415

    import eyenet.models  # noqa: F401, PLC0415

    conn.execute(text("DROP INDEX IF EXISTS uq_signing_pubkey_active"))
    tables = _filtered_tables(table_names)
    if tables:
        SQLModel.metadata.drop_all(conn, tables=tables)


_MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def upgrade_to_head(main_engine: Engine, audit_engine: Engine) -> None:
    """Apply all pending Postgres migrations to both DBs — the boot DDL path.

    Mirrors the SQLite backend: both sync engines are handed to ``env.py`` via
    ``config.attributes`` and the shared multi-db revision tree advances each
    physical DB's own ``alembic_version`` independently.
    """
    from alembic import command  # noqa: PLC0415
    from alembic.config import Config  # noqa: PLC0415

    cfg = Config()
    cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
    cfg.attributes["engines"] = {"main": main_engine, "audit": audit_engine}
    command.upgrade(cfg, "head")


__all__ = [
    "audit_url_for",
    "get_async_engine",
    "get_sync_engine",
    "upgrade_to_head",
]
