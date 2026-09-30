# SPDX-License-Identifier: AGPL-3.0-or-later
"""SQLite -> Postgres data move — synthetic regression probe (POSTGRES_PORT.md §7).

Seeds a small file-backed SQLite deployment, moves it into a fresh Postgres
deployment via ``migrate_sqlite_to_postgres``, and reconciles: row counts match
and the audit hash chain re-verifies on Postgres (proving the hash-critical
fields survived the typed round-trip). This is the CI-runnable companion to the
real-corpus validation (which runs against the operator's private snapshots and
is not committed).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from eyenet.contracts.audit import verify_chain
from eyenet.storage.factory import get_repository

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(180)]

psycopg = pytest.importorskip("psycopg")

try:
    from testcontainers.postgres import PostgresContainer
except Exception:  # pragma: no cover
    PostgresContainer = None  # type: ignore[assignment,misc]


@pytest.fixture(scope="module")
def pg_container() -> Iterator[Any]:
    if PostgresContainer is None:
        pytest.skip("testcontainers not installed")
    try:
        with PostgresContainer("postgres:16-alpine") as container:
            yield container
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"cannot start postgres container: {exc}")


@pytest.mark.asyncio
async def test_sqlite_to_postgres_move(
    pg_container: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eyenet.storage.postgres_repo._data_migrate import migrate_sqlite_to_postgres

    # --- seed a small SQLite source -------------------------------------------
    monkeypatch.setenv("EYENET_STORAGE_TYPE", "sqlite")
    src = get_repository(data_dir=tmp_path)
    actor = uuid.uuid4()
    for i in range(8):
        await src.append_audit(
            {
                "event": "evidence_access",
                "service": "engine",
                "instance_id": "eng_1",
                "subject_kind": "actor",
                "payload": {"i": i},
                "at": datetime(2026, 5, 4, 12, i, 0, tzinfo=UTC),
            }
        )
    await src.set_cursors_bulk(
        actor, [("chatty_member", datetime(2026, 5, 4, tzinfo=UTC), uuid.uuid4())]
    )
    await src.upsert_simhash(actor, "chatty_member", "00000000000000ff")

    # --- fresh Postgres destination -------------------------------------------
    host, port = pg_container.get_container_host_ip(), pg_container.get_exposed_port(5432)
    user, password = pg_container.username, pg_container.password
    admin = f"host={host} port={port} dbname={pg_container.dbname} user={user} password={password}"
    db = f"eyenet_move_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{db}"')
        conn.execute(f'CREATE DATABASE "{db}_audit"')
    url = f"postgresql://{user}:{password}@{host}:{port}/{db}"
    monkeypatch.setenv("EYENET_STORAGE_TYPE", "postgres")
    dst = get_repository(url=url)

    try:
        counts = migrate_sqlite_to_postgres(
            src_main=src.sync_engine,
            src_audit=src.audit_sync_engine,
            dst_main=dst.sync_engine,
            dst_audit=dst.audit_sync_engine,
        )
        assert counts["audit_log"] == 8
        assert counts["corpus_cursor"] == 1
        assert counts["vector_signature"] == 1

        # The audit chain must re-verify on Postgres — the hash covers `at` via
        # isoformat, so a broken datetime round-trip would fail here.
        rows = await dst.all_audit()
        ok, broken = verify_chain(rows)
        assert ok and broken is None
        assert [r.payload["i"] for r in rows] == list(range(8))
    finally:
        await src.close()
        await dst.close()
