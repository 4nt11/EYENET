"""SQLiteAuditStore — append-only, hash-chained, NDJSON-mirrored.

PLAN §9.3: every audit row is hash-chained inside a single transaction so
chain integrity is a write-time invariant, not a periodic check. Mirror to
NDJSON file with `0600` perms for offline forensic correlation.
"""

from __future__ import annotations

from datetime import UTC
from pathlib import Path
from threading import Lock
from typing import Any

from sqlalchemy.engine import Engine
from sqlmodel import Session, col, select

from eyenet.contracts.audit import GENESIS_PREV_HASH, AuditLogRow, compute_self_hash
from eyenet.models import AuditLogTable


class SQLiteAuditStore:
    """Append-only hash-chained audit log."""

    def __init__(self, engine: Engine, ndjson_path: Path | None = None) -> None:
        self._engine = engine
        self._ndjson = ndjson_path
        self._lock = Lock()
        if ndjson_path is not None:
            ndjson_path.parent.mkdir(parents=True, exist_ok=True)
            ndjson_path.touch(mode=0o600, exist_ok=True)

    def _last_hash(self, session: Session) -> str:
        # Order by id (UUIDv7 — time-ordered on creation) so the chain is
        # walked in append order regardless of `at` clock skew.
        last = session.exec(
            select(AuditLogTable).order_by(col(AuditLogTable.id).desc()).limit(1)
        ).first()
        return last.self_hash if last else GENESIS_PREV_HASH

    async def append(self, row_data: dict[str, Any]) -> AuditLogRow:
        """Compute the chain hashes and append.

        `row_data` carries every AuditLogRow field except `prev_hash` /
        `self_hash` — those are computed here.
        """

        with self._lock, Session(self._engine) as session:
            prev = self._last_hash(session)
            row = AuditLogRow(
                prev_hash=prev,
                self_hash="0" * 64,  # placeholder, recomputed
                **row_data,
            )
            row = row.model_copy(update={"self_hash": compute_self_hash(row)})
            session.add(AuditLogTable(**row.model_dump()))
            session.commit()
        if self._ndjson is not None:
            with self._ndjson.open("a", encoding="utf-8") as fh:
                fh.write(row.model_dump_json() + "\n")
        return row

    async def all(self) -> list[AuditLogRow]:
        with Session(self._engine) as session:
            tables = session.exec(select(AuditLogTable).order_by(col(AuditLogTable.id).asc())).all()
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
