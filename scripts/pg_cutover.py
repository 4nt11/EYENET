# SPDX-License-Identifier: AGPL-3.0-or-later
"""One-shot SQLite -> Postgres cutover orchestrator (POSTGRES_PORT.md §7).

The operator-facing wrapper around ``migrate_sqlite_to_postgres`` that §7.2
demanded: create the two destination databases, apply the Postgres baseline,
move every row, then VERIFY LOUD (per-table counts + both hash chains) and exit
non-zero on ANY mismatch. The library move function does not verify; this does.

    RUN WITH INGEST STOPPED, AGAINST A SNAPSHOT, NEVER THE LIVE WAL DB.

Make the snapshot first, while the stack is still up (VACUUM INTO is the only
sanctioned way to copy a live SQLite DB -- never cp a live -wal):

    mkdir -p snap
    docker compose -f deploy/docker/compose.yaml exec -T api \\
        sqlite3 /var/lib/eyenet/main.db  "VACUUM INTO '/var/lib/eyenet/_snap_main.db'"
    docker compose -f deploy/docker/compose.yaml exec -T api \\
        sqlite3 /var/lib/eyenet/audit.db "VACUUM INTO '/var/lib/eyenet/_snap_audit.db'"
    docker compose -f deploy/docker/compose.yaml cp api:/var/lib/eyenet/_snap_main.db  snap/main.db
    docker compose -f deploy/docker/compose.yaml cp api:/var/lib/eyenet/_snap_audit.db snap/audit.db

Then bring the stack DOWN and run:

    uv run python scripts/pg_cutover.py \\
        --sqlite-dir snap \\
        --pg-url postgresql://eyenet:PW@localhost:5432/eyenet

``--pg-url`` names the MAIN database; the audit DB is derived as ``<db>_audit``
(matching PostgresRepository). The maintenance connection used for CREATE
DATABASE defaults to the same server's ``postgres`` DB; override with
``--admin-url`` if your role connects elsewhere.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import psycopg
from sqlalchemy import text
from sqlalchemy.engine.url import make_url

import eyenet.models  # noqa: F401 -- registers every table on SQLModel.metadata
from eyenet.contracts.audit import verify_chain
from eyenet.storage.postgres_repo._data_migrate import migrate_sqlite_to_postgres
from eyenet.storage.postgres_repo.database import audit_url_for
from eyenet.storage.sqlite_repo.database import _AUDIT_TABLES, _MAIN_TABLES

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

    from eyenet.storage.repository import BaseRepository

_VECTOR_SIGNATURE = "vector_signature"


def _table_counts(engine: Engine, names: frozenset[str]) -> dict[str, int]:
    """Row count per existing table on a sync engine (missing tables skipped)."""
    from sqlmodel import SQLModel  # noqa: PLC0415

    present = [n for n in names if n in SQLModel.metadata.tables]
    counts: dict[str, int] = {}
    with engine.connect() as conn:
        for name in present:
            # name is from the internal _MAIN_TABLES/_AUDIT_TABLES constants, not user input.
            counts[name] = conn.execute(text(f"SELECT count(*) FROM {name}")).scalar_one()  # noqa: S608
    return counts


def _vector_signature_count(engine: Engine) -> int:
    with engine.connect() as conn:
        return conn.execute(text(f"SELECT count(*) FROM {_VECTOR_SIGNATURE}")).scalar_one()  # noqa: S608


def _ensure_databases(admin_url: str, main_db: str, audit_db: str, *, drop: bool) -> None:
    """CREATE the main + audit databases (idempotent). Needs the maintenance DB."""
    with psycopg.connect(admin_url, autocommit=True) as conn:
        for db in (main_db, audit_db):
            exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db,)).fetchone()
            if exists and drop:
                conn.execute(f'DROP DATABASE "{db}" WITH (FORCE)')
                exists = None
            if not exists:
                conn.execute(f'CREATE DATABASE "{db}"')
                print(f"  created database {db}")
            else:
                print(f"  database {db} already exists (reusing)")


def _admin_url_for(pg_url: str, override: str | None) -> str:
    if override:
        return override
    # Maintenance connection: same server/creds, the built-in `postgres` DB.
    # Plain libpq DSN for raw psycopg.connect (no SQLAlchemy +psycopg driver tag).
    return (
        make_url(pg_url)
        .set(drivername="postgresql", database="postgres")
        .render_as_string(hide_password=False)
    )


async def _verify(
    dst: BaseRepository, src_counts: dict[str, int], moved: dict[str, int]
) -> list[str]:
    """Return a list of failure strings; empty means the cutover verified."""
    failures: list[str] = []

    # 1. Per-table: source count == rows moved == rows now in Postgres.
    dst_main = _table_counts(dst.sync_engine, _MAIN_TABLES)
    dst_audit = _table_counts(dst.audit_sync_engine, _AUDIT_TABLES)
    dst_counts = {
        **dst_main,
        **dst_audit,
        _VECTOR_SIGNATURE: _vector_signature_count(dst.sync_engine),
    }
    for name, src_n in src_counts.items():
        moved_n = moved.get(name, 0)
        dst_n = dst_counts.get(name, 0)
        if not (src_n == moved_n == dst_n):
            failures.append(
                f"count mismatch {name}: source={src_n} moved={moved_n} postgres={dst_n}"
            )

    # 2. Audit hash chain must re-verify on Postgres (proves the typed round-trip
    #    preserved every hash-covered field, timestamps included).
    rows = await dst.all_audit()
    ok, broken = verify_chain(rows)
    if not ok:
        failures.append(f"audit chain broken on Postgres at seq={broken}")

    # 3. File-access journal chain (second hash chain) must re-verify too.
    if not await dst.verify_file_access_chain():
        failures.append("file-access journal chain failed to verify on Postgres")

    return failures


async def _run(args: argparse.Namespace) -> int:
    snap = Path(args.sqlite_dir)
    for fn in ("main.db", "audit.db"):
        if not (snap / fn).is_file():
            print(
                f"ERROR: {snap / fn} not found. Point --sqlite-dir at a VACUUM INTO snapshot.",
                file=sys.stderr,
            )
            return 2

    main_url = make_url(args.pg_url)
    main_db = main_url.database
    if not main_db:
        print("ERROR: --pg-url must name a database", file=sys.stderr)
        return 2
    audit_db = make_url(audit_url_for(args.pg_url)).database

    masked = main_url.set(password="***")  # noqa: S106 -- masking for display, not a credential
    print(f"==> destination: {masked}  (+ {audit_db})")
    print("==> creating databases")
    _ensure_databases(
        _admin_url_for(args.pg_url, args.admin_url), main_db, audit_db, drop=args.drop_existing
    )

    # Source: SQLite snapshot. Dest: Postgres (runs the baseline on construct).
    from eyenet.storage.factory import get_repository  # noqa: PLC0415

    os.environ["EYENET_STORAGE_TYPE"] = "sqlite"
    src = get_repository(data_dir=snap)
    os.environ["EYENET_STORAGE_TYPE"] = "postgres"
    dst = get_repository(url=args.pg_url)

    try:
        src_counts = {
            **_table_counts(src.sync_engine, _MAIN_TABLES),
            **_table_counts(src.audit_sync_engine, _AUDIT_TABLES),
            _VECTOR_SIGNATURE: _vector_signature_count(src.sync_engine),
        }
        print(f"==> source rows: {sum(src_counts.values())} across {len(src_counts)} tables")

        print("==> moving rows")
        moved = migrate_sqlite_to_postgres(
            src_main=src.sync_engine,
            src_audit=src.audit_sync_engine,
            dst_main=dst.sync_engine,
            dst_audit=dst.audit_sync_engine,
            progress=lambda name, n: print(f"  {name}: {n}") if n else None,
        )

        print("==> verifying (counts + both hash chains)")
        failures = await _verify(dst, src_counts, moved)
    finally:
        await src.close()
        await dst.close()

    if failures:
        print("\nCUTOVER FAILED -- do NOT repoint the stack:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1

    print(f"\nOK: {sum(src_counts.values())} rows moved, both hash chains verify on Postgres.")
    print("Safe to repoint the stack at Postgres (EYENET_STORAGE_TYPE=postgres).")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--sqlite-dir",
        required=True,
        help="dir holding the VACUUM INTO snapshot (main.db + audit.db)",
    )
    p.add_argument(
        "--pg-url", required=True, help="postgresql://user:pw@host:5432/eyenet (names the MAIN db)"
    )
    p.add_argument(
        "--admin-url",
        help="maintenance connection for CREATE DATABASE (default: same server, 'postgres' db)",
    )
    p.add_argument(
        "--drop-existing",
        action="store_true",
        help="DROP the target databases first (destructive, dry-run only)",
    )
    return asyncio.run(_run(p.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
