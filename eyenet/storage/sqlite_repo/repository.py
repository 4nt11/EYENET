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
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

from eyenet.contracts.audit import (
    GENESIS_PREV_HASH,
    AuditLogRow,
    compute_self_hash,
)
from eyenet.models import CorpusCursorTable, FileAccessJournalTable
from eyenet.models.file_access import FileAccessAcknowledgmentTable
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
from eyenet.storage.sqlmodel_repo._helpers import safe_session
from eyenet.storage.sqlmodel_repo.file_access import (
    GENESIS_JOURNAL_HASH,
    FileAccessJournalError,
    _PreparedJournalRow,
)

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

_FILE_ACCESS_INSERT_SQL = (
    "INSERT INTO file_access_journal ("
    "access_id, audit_event_id, user_id, grant_id, content_hash, "
    "content_size, content_mime, tier, served_at, served_via, "
    "acknowledgment_id, operator_signature, signing_pubkey_fingerprint, "
    "prev_journal_hash, self_hash"
    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
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

    async def _append_file_access_locked(
        self,
        prepared: _PreparedJournalRow,
        *,
        require_nonce: bool,
        now: datetime,
    ) -> UUID:
        """SQLite hash-chained file-access journal append (M9.B2).

        Mirrors ``_append_audit_locked`` EXACTLY for the SECOND chain: the
        in-process ``asyncio.Lock`` serializes coroutines on the audit engine,
        and ``BEGIN IMMEDIATE`` on the raw aiosqlite cursor acquires SQLite's
        RESERVED lock so concurrent processes serialize at the file. The
        (conditional) nonce consume, chain head read, ``self_hash`` compute,
        INSERT and COMMIT all happen inside the one ``BEGIN IMMEDIATE``
        transaction so consume+append are ATOMIC and the chain can never fork.
        """

        async with self._audit_write_lock:
            return await self._append_file_access_chain(
                prepared, require_nonce=require_nonce, now=now
            )

    async def _append_file_access_chain(
        self,
        prepared: _PreparedJournalRow,
        *,
        require_nonce: bool,
        now: datetime,
    ) -> UUID:
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
                    # Atomic nonce consume INSIDE this serialized transaction
                    # (FIX 1): conditional compare-and-swap. If it doesn't claim
                    # exactly one live, unconsumed, unexpired nonce we roll the
                    # WHOLE transaction back — nonce stays unconsumed (retryable)
                    # and no journal row is written. No burned-nonce-without-row,
                    # no row-without-consumed-nonce (double-spend).
                    if require_nonce:
                        await self._consume_nonce_locked(cur, prepared.acknowledgment_id, now)
                    await cur.execute(
                        "SELECT self_hash FROM file_access_journal ORDER BY rowid DESC LIMIT 1"
                    )
                    last = await cur.fetchone()
                    prev = bytes(last[0]) if last is not None else GENESIS_JOURNAL_HASH
                    self_hash = prepared.self_hash(prev)
                    values = self._file_access_insert_values(prepared, prev, self_hash)
                    await cur.execute(_FILE_ACCESS_INSERT_SQL, values)
                    await cur.execute("COMMIT")
                except BaseException:
                    with contextlib.suppress(Exception):
                        await cur.execute("ROLLBACK")
                    raise
                finally:
                    await cur.close()
                return prepared.access_id
            finally:
                driver.isolation_level = prior_isolation
        finally:
            raw_conn.close()

    @staticmethod
    async def _consume_nonce_locked(cur: Any, nonce: UUID | None, now: datetime) -> None:
        """Conditional single-use nonce consume on the already-open cursor.

        Runs INSIDE the caller's ``BEGIN IMMEDIATE`` transaction (raw aiosqlite
        cursor) so it is atomic with the journal INSERT. The ``consumed_at IS
        NULL AND expires_at > :now`` predicate rejects a double-spend, an
        expired nonce, and an unknown nonce in one statement. If rowcount != 1
        we raise :class:`FileAccessJournalError`; the caller's ``except`` rolls
        the whole transaction back, so the nonce stays unconsumed.

        Dialect-specific (raw-cursor + the SQLite column type processors for the
        UUID/datetime binds) — lives here, never in the mixin (Rule 1).
        """
        if nonce is None:  # pragma: no cover — guarded upstream by record_access
            raise FileAccessJournalError("nonce required but acknowledgment_id is None")
        from sqlalchemy import inspect as sa_inspect  # noqa: PLC0415

        dialect = SQLiteRepository._sqlite_dialect()
        ack_cols = sa_inspect(FileAccessAcknowledgmentTable).local_table.c

        def _enc(col_name: str, value: Any) -> Any:
            proc = ack_cols[col_name].type.bind_processor(dialect)
            return proc(value) if proc is not None else value

        nonce_enc = _enc("nonce", nonce)
        now_enc = _enc("consumed_at", now)
        await cur.execute(
            "UPDATE file_access_acknowledgment SET consumed_at = ? "
            "WHERE nonce = ? AND consumed_at IS NULL AND expires_at > ?",
            (now_enc, nonce_enc, now_enc),
        )
        if int(cur.rowcount) != 1:
            raise FileAccessJournalError(
                f"acknowledgment nonce {nonce} is used, expired, or unknown"
            )

    @staticmethod
    def _file_access_insert_values(
        prepared: _PreparedJournalRow,
        prev_journal_hash: bytes,
        self_hash: bytes,
    ) -> tuple[Any, ...]:
        """Bind values for the raw journal INSERT, encoded via the column
        type processors so the stored bytes are byte-identical to what the ORM
        reads back (UUID -> 32-hex string, Enum -> NAME, datetime -> ISO).
        """
        from sqlalchemy import inspect as sa_inspect  # noqa: PLC0415

        dialect = SQLiteRepository._sqlite_dialect()
        cols = sa_inspect(FileAccessJournalTable).local_table.c

        def _enc(col_name: str, value: Any) -> Any:
            proc = cols[col_name].type.bind_processor(dialect)
            return proc(value) if proc is not None else value

        return (
            _enc("access_id", prepared.access_id),
            _enc("audit_event_id", prepared.audit_event_id),
            _enc("user_id", prepared.user_id),
            _enc("grant_id", prepared.grant_id),
            _enc("content_hash", prepared.content_hash),
            prepared.content_size,
            prepared.content_mime,
            _enc("tier", prepared.tier),
            _enc("served_at", prepared.served_at),
            _enc("served_via", prepared.served_via),
            _enc("acknowledgment_id", prepared.acknowledgment_id),
            _enc("operator_signature", prepared.operator_signature),
            prepared.signing_pubkey_fingerprint,
            _enc("prev_journal_hash", prev_journal_hash),
            _enc("self_hash", self_hash),
        )

    @staticmethod
    def _sqlite_dialect() -> Any:
        from sqlalchemy.dialects.sqlite import dialect as sqlite_dialect  # noqa: PLC0415

        return sqlite_dialect()

    async def set_cursors_bulk(
        self,
        actor_id: UUID,
        updates: Sequence[tuple[str, datetime, UUID]],
    ) -> None:
        """SQLite override: INSERT ... ON CONFLICT for race-safe bulk upsert.

        The generic mixin uses SELECT-then-add which races under concurrent
        dispatches for the same actor (UNIQUE violation). SQLite expresses
        an atomic upsert via ``ON CONFLICT (actor_id, primitive_name) DO
        UPDATE SET ...``.
        """
        if not updates:
            return
        rows = [
            {
                "actor_id": actor_id,
                "primitive_name": name,
                "last_processed_msg_ts": last_ts,
                "last_processed_msg_id": last_msg_id,
            }
            for name, last_ts, last_msg_id in updates
        ]
        stmt = sqlite_insert(CorpusCursorTable).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["actor_id", "primitive_name"],
            set_={
                "last_processed_msg_ts": stmt.excluded.last_processed_msg_ts,
                "last_processed_msg_id": stmt.excluded.last_processed_msg_id,
            },
        )
        async with safe_session(self._session_factory) as session:
            await session.exec(stmt)
            await session.commit()

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
