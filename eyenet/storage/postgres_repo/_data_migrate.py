# SPDX-License-Identifier: AGPL-3.0-or-later
"""One-shot SQLite -> Postgres data move (POSTGRES_PORT.md §7).

Copies an EXISTING SQLite deployment's rows into a freshly-migrated Postgres
deployment, table by table, through the shared ``SQLModel.metadata`` typed Core
tables — so every value is decoded by SQLite's result processor and re-encoded
by Postgres's bind processor (UUID, JSON, bytea, datetime) with no hand mapping.

Safety (from prior scars — see the storage memories):
  * Operate on a COPY/snapshot, never the live WAL DB. This module only READS the
    source; the caller passes a snapshot's engines.
  * The destination Postgres DBs must already exist and be migrated to head
    (an empty schema); this only moves rows.

Design notes:
  * FK-safe order comes from ``metadata.sorted_tables`` (parents first), split
    into the two physical DBs. FK checks are additionally disabled for the load
    (``session_replication_role = replica``) so any residual ordering edge or
    self-reference can't block the bulk copy. Requires a superuser/replication
    role on the destination (the operator's cutover role; the test container's
    is).
  * GENERATED columns (the active_* partial-unique helpers) are EXCLUDED from the
    insert — Postgres recomputes them.
  * ``seq`` IS copied verbatim (a plain column, not an identity), preserving the
    exact hash-chain walk order. PKs are UUIDs, so there are no identity
    sequences to reset.
  * ``vector_signature`` lives outside ``SQLModel.metadata`` (raw DDL), so it is
    copied separately.

  # ponytail: typed Core executemany, batched. COPY (asyncpg copy_records_to_table
  # / psycopg copy) is the firehose upgrade if a large cutover is too slow; wire
  # it per-table only once measured.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from sqlalchemy import Table, select, text
from sqlalchemy.engine import Connection, Engine
from sqlmodel import SQLModel

import eyenet.models  # noqa: F401 — registers every table on SQLModel.metadata
from eyenet.storage.sqlite_repo.database import _AUDIT_TABLES, _MAIN_TABLES

_log = logging.getLogger(__name__)

_VECTOR_SIGNATURE = "vector_signature"

ProgressFn = Callable[[str, int], None]


def _copy_table_into(table: Table, src: Engine, dst_conn: Connection, batch_size: int) -> int:
    """Stream one table from ``src`` into the open ``dst_conn`` in batches."""
    cols = [c for c in table.columns if c.computed is None]
    col_names = [c.name for c in cols]
    ins = table.insert()
    total = 0
    with src.connect() as sconn:
        result = sconn.execute(select(*cols))
        while True:
            batch = result.fetchmany(batch_size)
            if not batch:
                break
            dst_conn.execute(ins, [dict(zip(col_names, row, strict=True)) for row in batch])
            total += len(batch)
    return total


def _copy_vector_signature(src: Engine, dst: Engine) -> int:
    """Copy the raw (non-ORM) vector_signature side-table (main DB)."""
    with src.connect() as s:
        rows = s.execute(
            text("SELECT actor_id, primitive_name, simhash FROM vector_signature")
        ).fetchall()
    if rows:
        with dst.begin() as d:
            d.execute(
                text(
                    "INSERT INTO vector_signature (actor_id, primitive_name, simhash) "
                    "VALUES (:a, :p, :s)"
                ),
                [{"a": r[0], "p": r[1], "s": r[2]} for r in rows],
            )
    return len(rows)


def migrate_sqlite_to_postgres(
    *,
    src_main: Engine,
    src_audit: Engine,
    dst_main: Engine,
    dst_audit: Engine,
    batch_size: int = 5000,
    progress: ProgressFn | None = None,
) -> dict[str, int]:
    """Move every row from the SQLite snapshot into the Postgres deployment.

    Engines are sync (psycopg on the destination). Returns a per-table row-count
    map (including ``vector_signature``) for the caller to reconcile against the
    source. Run with ingest STOPPED.
    """
    tables = SQLModel.metadata.sorted_tables
    counts: dict[str, int] = {}

    for subset_names, src, dst in (
        (_MAIN_TABLES, src_main, dst_main),
        (_AUDIT_TABLES, src_audit, dst_audit),
    ):
        subset = [t for t in tables if t.name in subset_names]
        with dst.begin() as dconn:
            # Disable FK triggers for the bulk load; sorted_tables already orders
            # parents first, this just removes any residual edge as a blocker.
            dconn.execute(text("SET session_replication_role = replica"))
            for table in subset:
                n = _copy_table_into(table, src, dconn, batch_size)
                counts[table.name] = n
                if progress is not None:
                    progress(table.name, n)
            dconn.execute(text("SET session_replication_role = DEFAULT"))

    counts[_VECTOR_SIGNATURE] = _copy_vector_signature(src_main, dst_main)
    if progress is not None:
        progress(_VECTOR_SIGNATURE, counts[_VECTOR_SIGNATURE])
    return counts


__all__ = ["migrate_sqlite_to_postgres"]
