# SPDX-License-Identifier: AGPL-3.0-or-later
"""SQLiteRepository — concrete SQLite override of SQLModelRepository.

Overrides only the dialect-specific surface: the audit ``BEGIN IMMEDIATE``
write path (raw aiosqlite cursor, hash-chained inside one transaction) and
engine construction. Everything else is inherited from the per-domain mixins.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid as _uuid
from datetime import UTC
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

from eyenet.contracts.audit import (
    GENESIS_PREV_HASH,
    AuditLogRow,
    compute_self_hash,
)
from eyenet.storage.sqlite_repo.database import (
    get_async_engine,
    get_sync_engine,
    init_audit_db,
    init_lock,
    init_main_db,
    open_in_memory_async_engine,
    open_in_memory_sync_engine,
)
from eyenet.storage.sqlmodel_repo import SQLModelRepository

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


class SQLiteRepository(SQLModelRepository):
    """SQLite-backed repository: 2 physical DBs (main + audit), async engines."""

    def __init__(
        self,
        *,
        data_dir: Path | None = None,
        in_memory: bool = False,
        ndjson_path: Path | None = None,
    ) -> None:
        self._data_dir: Path | None
        if in_memory:
            self._data_dir = None
            # Unique cache names per instance so concurrent tests don't share
            # state through the in-memory DB.
            main_name = f"eyenet-main-{_uuid.uuid4().hex}"
            audit_name = f"eyenet-audit-{_uuid.uuid4().hex}"
            self.sync_engine = open_in_memory_sync_engine(main_name)
            self.audit_sync_engine = open_in_memory_sync_engine(audit_name)
            init_main_db(self.sync_engine)
            init_audit_db(self.audit_sync_engine)
            self.engine = open_in_memory_async_engine(main_name)
            self.audit_engine = open_in_memory_async_engine(audit_name)
        else:
            if data_dir is None:
                raise ValueError("SQLiteRepository requires data_dir when in_memory=False")
            self._data_dir = data_dir
            with init_lock(data_dir):
                self.sync_engine = get_sync_engine(data_dir / "main.db")
                self.audit_sync_engine = get_sync_engine(data_dir / "audit.db")
                init_main_db(self.sync_engine)
                init_audit_db(self.audit_sync_engine)
                self.engine = get_async_engine(data_dir / "main.db")
                self.audit_engine = get_async_engine(data_dir / "audit.db")

        self._session_factory = async_sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )
        self._audit_session_factory = async_sessionmaker(
            self.audit_engine, class_=AsyncSession, expire_on_commit=False
        )
        self._audit_write_lock = asyncio.Lock()
        self._ndjson = ndjson_path
        if ndjson_path is not None:
            ndjson_path.parent.mkdir(parents=True, exist_ok=True)
            ndjson_path.touch(mode=0o600, exist_ok=True)

    @property
    def data_dir(self) -> Path | None:
        return self._data_dir

    async def _append_audit_locked(self, row_data: dict[str, Any]) -> AuditLogRow:
        """SQLite hash-chained audit append via raw aiosqlite cursor.

        ``BEGIN IMMEDIATE`` acquires the RESERVED lock so concurrent writers
        across processes serialize at the SQLite layer. The in-process
        ``asyncio.Lock`` prevents two coroutines in this process from racing
        on the same raw connection.
        """

        async with self._audit_write_lock:
            row = await self._append_chain(row_data)
        if self._ndjson is not None:
            await asyncio.to_thread(self._write_ndjson, row)
        return row

    async def _append_chain(self, row_data: dict[str, Any]) -> AuditLogRow:
        raw_conn = await self.audit_engine.raw_connection()
        try:
            driver = raw_conn.driver_connection  # aiosqlite.Connection
            if driver is None:  # pragma: no cover
                raise RuntimeError("audit engine returned no DBAPI connection")
            prior_isolation = driver.isolation_level
            driver.isolation_level = None
            try:
                cur = await driver.cursor()
                try:
                    await cur.execute("BEGIN IMMEDIATE")
                    await cur.execute("SELECT self_hash FROM audit_log ORDER BY rowid DESC LIMIT 1")
                    last = await cur.fetchone()
                    prev = last[0] if last is not None else GENESIS_PREV_HASH
                    row = AuditLogRow(
                        prev_hash=prev,
                        self_hash="0" * 64,
                        **row_data,
                    )
                    row = row.model_copy(update={"self_hash": compute_self_hash(row)})
                    data = row.model_dump(mode="json")
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
                    await cur.execute(_AUDIT_INSERT_SQL, values)
                    await cur.execute("COMMIT")
                except BaseException:
                    with contextlib.suppress(Exception):
                        await cur.execute("ROLLBACK")
                    raise
                finally:
                    await cur.close()
                return row
            finally:
                driver.isolation_level = prior_isolation
        finally:
            raw_conn.close()

    def _write_ndjson(self, row: AuditLogRow) -> None:
        if self._ndjson is None:
            return
        with self._ndjson.open("a", encoding="utf-8") as fh:
            fh.write(row.model_dump_json() + "\n")

    async def close(self) -> None:
        await self.engine.dispose()
        await self.audit_engine.dispose()
        with contextlib.suppress(Exception):
            self.sync_engine.dispose()
        with contextlib.suppress(Exception):
            self.audit_sync_engine.dispose()


# Silence UTC unused import on linters that miss the docstring usage.
_ = UTC

__all__ = ["SQLiteRepository"]
