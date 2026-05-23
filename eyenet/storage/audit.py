"""SQLiteAuditStore — append-only, hash-chained, NDJSON-mirrored.

PLAN §9.3: every audit row is hash-chained inside a single transaction so
chain integrity is a write-time invariant, not a periodic check. Mirror to
NDJSON file with `0600` perms for offline forensic correlation.
"""

from __future__ import annotations

import contextlib
import json
from datetime import UTC
from pathlib import Path
from threading import Lock
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from eyenet.contracts.audit import GENESIS_PREV_HASH, AuditLogRow, compute_self_hash
from eyenet.models import AuditLogTable

# Static INSERT for audit_log. Column identifiers cannot be SQL-bound, so the
# safest construction is a hand-written statement that pins every column name
# at source-read time and uses placeholders only for values. Adding/removing
# a column requires editing this constant AND the matching value list in
# `_append_locked` — that coupling is intentional: it makes a contract change
# visible as a code change, not a silent string-template recomposition.
_AUDIT_INSERT_SQL = (
    "INSERT INTO audit_log ("
    "id, event, service, instance_id, system_user_id, subject_kind, "
    "subject_id, evidence_ref, trace_id, span_id, payload, at, "
    "prev_hash, self_hash"
    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)
_AUDIT_INSERT_COLS: tuple[str, ...] = (
    "id",
    "event",
    "service",
    "instance_id",
    "system_user_id",
    "subject_kind",
    "subject_id",
    "evidence_ref",
    "trace_id",
    "span_id",
    "payload",
    "at",
    "prev_hash",
    "self_hash",
)


class SQLiteAuditStore:
    """Append-only hash-chained audit log."""

    def __init__(self, engine: Engine, ndjson_path: Path | None = None) -> None:
        self._engine = engine
        self._ndjson = ndjson_path
        self._lock = Lock()
        if ndjson_path is not None:
            ndjson_path.parent.mkdir(parents=True, exist_ok=True)
            ndjson_path.touch(mode=0o600, exist_ok=True)

    async def append(self, row_data: dict[str, Any]) -> AuditLogRow:
        """Compute the chain hashes and append.

        `row_data` carries every AuditLogRow field except `prev_hash` /
        `self_hash` — those are computed here.

        SELECT-last-hash → INSERT runs inside an explicit `BEGIN IMMEDIATE`
        on a raw DBAPI connection so concurrent writers across processes
        serialize at the SQLite RESERVED-lock layer. Without this, two
        `eyenet` processes can both read the same parent before either
        commits and produce a forked chain. Read paths stay on SQLAlchemy
        Sessions — WAL snapshots let them run concurrently with this writer.
        """

        with self._lock:
            row = self._append_locked(row_data)
        if self._ndjson is not None:
            with self._ndjson.open("a", encoding="utf-8") as fh:
                fh.write(row.model_dump_json() + "\n")
        return row

    def _append_locked(self, row_data: dict[str, Any]) -> AuditLogRow:
        raw = self._engine.raw_connection()
        driver = raw.driver_connection
        if driver is None:  # pragma: no cover — pysqlite always supplies one
            raise RuntimeError("audit engine returned no DBAPI connection")
        prior_isolation = driver.isolation_level
        # Disable pysqlite's implicit-BEGIN so we control the transaction
        # explicitly. Restored in the finally below before the connection
        # returns to the pool.
        driver.isolation_level = None
        try:
            cur = driver.cursor()
            try:
                cur.execute("BEGIN IMMEDIATE")
                # Order by SQLite's implicit rowid — it is INSERT-commit-ordered
                # under BEGIN IMMEDIATE. UUIDv7 ids would also work within a
                # single process, but across processes two UUIDv7s generated
                # in the same millisecond can come out of order, scrambling the
                # chain when reconstructed.
                cur.execute("SELECT self_hash FROM audit_log ORDER BY rowid DESC LIMIT 1")
                last = cur.fetchone()
                prev = last[0] if last is not None else GENESIS_PREV_HASH
                row = AuditLogRow(
                    prev_hash=prev,
                    self_hash="0" * 64,  # placeholder, recomputed below
                    **row_data,
                )
                row = row.model_copy(update={"self_hash": compute_self_hash(row)})
                data = row.model_dump(mode="json")
                # Drift guard: if a future contract adds a field, fail loud
                # here rather than silently dropping the column.
                if set(data.keys()) != set(_AUDIT_INSERT_COLS):
                    raise RuntimeError(
                        "AuditLogRow fields drifted from _AUDIT_INSERT_COLS — "
                        f"row={sorted(data.keys())} "
                        f"static={sorted(_AUDIT_INSERT_COLS)}"
                    )
                values = tuple(
                    json.dumps(data[c]) if isinstance(data[c], (dict, list)) else data[c]
                    for c in _AUDIT_INSERT_COLS
                )
                cur.execute(_AUDIT_INSERT_SQL, values)
                cur.execute("COMMIT")
            except Exception:
                with contextlib.suppress(Exception):
                    cur.execute("ROLLBACK")
                raise
            finally:
                cur.close()
            return row
        finally:
            driver.isolation_level = prior_isolation
            raw.close()

    async def all(self) -> list[AuditLogRow]:
        with Session(self._engine) as session:
            # Order by SQLite's implicit rowid (= INSERT-commit order under our
            # BEGIN IMMEDIATE write path). See `_append_locked` for the reason.
            tables = session.exec(select(AuditLogTable).order_by(text("rowid ASC"))).all()
            rows: list[AuditLogRow] = []
            for t in tables:
                data = t.model_dump()
                # SQLite stores naive datetimes; restore UTC tz so the
                # canonical hash matches the write-time form.
                if data["at"].tzinfo is None:
                    data["at"] = data["at"].replace(tzinfo=UTC)
                rows.append(AuditLogRow.model_validate(data))
            return rows


__all__ = ["SQLiteAuditStore"]
