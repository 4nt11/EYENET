# SPDX-License-Identifier: AGPL-3.0-or-later
"""PostgresRepository — concrete PostgreSQL override of SQLModelRepository.

Overrides only the dialect-specific surface: engine construction and the two
hash-chained single-writer append paths (audit + file-access journal). Where
SQLite uses ``BEGIN IMMEDIATE`` on a raw aiosqlite cursor, Postgres uses a
transaction-scoped advisory lock (``pg_advisory_xact_lock``) — it serializes
writers across processes and auto-releases on commit/rollback, so a crashed
writer never strands the lock. The in-process ``asyncio.Lock`` still serializes
coroutines in one process.

Everything else is inherited from the per-domain mixins:
  * ``_body_match`` — the generic ANSI ``LIKE`` fallback (tsvector/GIN is a future
    optimization, POSTGRES_PORT.md §2.5).
  * ``put_observations_bulk`` — the generic one-session-many-inserts path.
    # ponytail: COPY (asyncpg copy_records_to_table) is the firehose upgrade;
    # add it here only once ingest throughput measurably needs it (§2.6).
  * vector search — the mixin SQL (``hamming64`` + ``ON CONFLICT``) is portable;
    the backend supplies the ``hamming64`` function via its baseline DDL.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine.url import URL
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel import col
from sqlmodel.ext.asyncio.session import AsyncSession

from eyenet.contracts.audit import (
    GENESIS_PREV_HASH,
    AuditLogRow,
    compute_self_hash,
)
from eyenet.models import (
    AuditLogTable,
    CorpusCursorTable,
    FileAccessJournalTable,
)
from eyenet.models.file_access import FileAccessAcknowledgmentTable
from eyenet.storage.postgres_repo.database import (
    audit_url_for,
    get_async_engine,
    get_sync_engine,
    upgrade_to_head,
)
from eyenet.storage.sqlmodel_repo import SQLModelRepository
from eyenet.storage.sqlmodel_repo._helpers import safe_session
from eyenet.storage.sqlmodel_repo.file_access import (
    GENESIS_JOURNAL_HASH,
    FileAccessJournalError,
    _PreparedJournalRow,
)

# Fixed advisory-lock keys — one per chain, so audit appends and file-access
# appends serialize INDEPENDENTLY (both live in the audit DB). Arbitrary but
# stable int64 constants.
_AUDIT_LOCK_KEY = 8074920100000001
_FILE_ACCESS_LOCK_KEY = 8074920100000002


class PostgresRepository(SQLModelRepository):
    """Postgres-backed repository: 2 databases (main + audit), asyncpg engines."""

    def __init__(
        self,
        *,
        url: str | URL | None = None,
        audit_url: str | URL | None = None,
        pool_size: int = 5,
        max_overflow: int = 10,
        ndjson_path: Path | None = None,
    ) -> None:
        url = url if url is not None else os.environ.get("EYENET_PG_URL")
        if not url:
            raise ValueError("PostgresRepository requires url= or EYENET_PG_URL")
        resolved_audit = audit_url if audit_url is not None else audit_url_for(url)

        # Sync engines first: run the DDL baseline (both DBs must already exist).
        self.sync_engine = get_sync_engine(url)
        self.audit_sync_engine = get_sync_engine(resolved_audit)
        upgrade_to_head(self.sync_engine, self.audit_sync_engine)

        # Async engines for the request path.
        self.engine = get_async_engine(url, pool_size=pool_size, max_overflow=max_overflow)
        self.audit_engine = get_async_engine(
            resolved_audit, pool_size=pool_size, max_overflow=max_overflow
        )

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
        return None

    # --- audit chain ---------------------------------------------------------

    async def _append_audit_locked(self, row_data: dict[str, Any]) -> AuditLogRow:
        """Advisory-locked, hash-chained audit append (Postgres)."""
        async with self._audit_write_lock:
            row = await self._append_chain(row_data)
        if self._ndjson is not None:
            await asyncio.to_thread(self._write_ndjson, row)
        return row

    async def _append_chain(self, row_data: dict[str, Any]) -> AuditLogRow:
        async with self._audit_session_factory() as session, session.begin():
            # Transaction-scoped: serializes cross-process writers, auto-released
            # on COMMIT below. The SELECT-compute-INSERT is atomic under it, so
            # the chain can never fork.
            await session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _AUDIT_LOCK_KEY})
            tip = (
                await session.execute(
                    select(AuditLogTable.seq, AuditLogTable.self_hash)
                    .order_by(col(AuditLogTable.seq).desc())
                    .limit(1)
                )
            ).first()
            next_seq = 1 if tip is None else int(tip[0]) + 1
            prev = tip[1] if tip is not None else GENESIS_PREV_HASH
            row = AuditLogRow(prev_hash=prev, self_hash="0" * 64, **row_data)
            row = row.model_copy(update={"self_hash": compute_self_hash(row)})
            # ORM insert maps every AuditLogRow field to its column by name and
            # handles JSON/UUID/timestamp encoding; seq is the one column the
            # contract does not carry, bound explicitly.
            session.add(AuditLogTable(**row.model_dump(), seq=next_seq))
        return row

    def _write_ndjson(self, row: AuditLogRow) -> None:
        if self._ndjson is None:
            return
        with self._ndjson.open("a", encoding="utf-8") as fh:
            fh.write(row.model_dump_json() + "\n")

    # --- file-access journal chain ------------------------------------------

    async def _append_file_access_locked(
        self,
        prepared: _PreparedJournalRow,
        *,
        require_nonce: bool,
        now: datetime,
    ) -> UUID:
        """Advisory-locked file-access journal append (second chain, Postgres).

        The (conditional) nonce consume, chain-head read, ``self_hash`` compute
        and INSERT run inside ONE advisory-locked transaction, so consume+append
        are atomic — no burned-nonce-without-row, no double-spend.
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
        async with self._audit_session_factory() as session, session.begin():
            await session.execute(
                text("SELECT pg_advisory_xact_lock(:k)"), {"k": _FILE_ACCESS_LOCK_KEY}
            )
            if require_nonce:
                await self._consume_nonce_locked(session, prepared.acknowledgment_id, now)
            tip = (
                await session.execute(
                    select(FileAccessJournalTable.seq, FileAccessJournalTable.self_hash)
                    .order_by(col(FileAccessJournalTable.seq).desc())
                    .limit(1)
                )
            ).first()
            next_seq = 1 if tip is None else int(tip[0]) + 1
            prev = bytes(tip[1]) if tip is not None else GENESIS_JOURNAL_HASH
            self_hash = prepared.self_hash(prev)
            session.add(
                FileAccessJournalTable(
                    access_id=prepared.access_id,
                    audit_event_id=prepared.audit_event_id,
                    user_id=prepared.user_id,
                    grant_id=prepared.grant_id,
                    content_hash=prepared.content_hash,
                    content_size=prepared.content_size,
                    content_mime=prepared.content_mime,
                    tier=prepared.tier,
                    served_at=prepared.served_at,
                    served_via=prepared.served_via,
                    acknowledgment_id=prepared.acknowledgment_id,
                    operator_signature=prepared.operator_signature,
                    signing_pubkey_fingerprint=prepared.signing_pubkey_fingerprint,
                    prev_journal_hash=prev,
                    self_hash=self_hash,
                    seq=next_seq,
                )
            )
        return prepared.access_id

    @staticmethod
    async def _consume_nonce_locked(
        session: AsyncSession, nonce: UUID | None, now: datetime
    ) -> None:
        """Conditional single-use nonce consume, atomic with the append.

        ``consumed_at IS NULL AND expires_at > now`` rejects a double-spend, an
        expired nonce and an unknown nonce in one statement; rowcount != 1 raises
        so the caller's transaction rolls back and the nonce stays unconsumed.
        """
        if nonce is None:  # pragma: no cover — guarded upstream by record_access
            raise FileAccessJournalError("nonce required but acknowledgment_id is None")
        result = await session.execute(
            update(FileAccessAcknowledgmentTable)
            .where(
                col(FileAccessAcknowledgmentTable.nonce) == nonce,
                col(FileAccessAcknowledgmentTable.consumed_at).is_(None),
                col(FileAccessAcknowledgmentTable.expires_at) > now,
            )
            .values(consumed_at=now)
        )
        if result.rowcount != 1:
            raise FileAccessJournalError(
                f"acknowledgment nonce {nonce} is used, expired, or unknown"
            )

    # --- dialect upsert ------------------------------------------------------

    async def set_cursors_bulk(
        self,
        actor_id: UUID,
        updates: Sequence[tuple[str, datetime, UUID]],
    ) -> None:
        """Postgres override: INSERT ... ON CONFLICT for race-safe bulk upsert."""
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
        stmt = pg_insert(CorpusCursorTable).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["actor_id", "primitive_name"],
            set_={
                "last_processed_msg_ts": stmt.excluded.last_processed_msg_ts,
                "last_processed_msg_id": stmt.excluded.last_processed_msg_id,
            },
        )
        async with safe_session(self._session_factory) as session:
            await session.execute(stmt)
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

__all__ = ["PostgresRepository"]
