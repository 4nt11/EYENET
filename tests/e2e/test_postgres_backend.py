# SPDX-License-Identifier: AGPL-3.0-or-later
"""PostgresRepository — live-backend probe via testcontainers.

Boots a real PostgreSQL in a container and drives the concrete backend through
the factory (``EYENET_STORAGE_TYPE=postgres``). Marked ``e2e`` (spins a
container, slow); each test gets its OWN pair of fresh databases so the chains
start empty and tests don't cross-contaminate.

Pins the Postgres-specific surface the SQLite suite cannot reach:
  * the advisory-lock (``pg_advisory_xact_lock``) hash-chained audit append,
  * the same for the file-access journal (the second chain),
  * the ``INSERT ... ON CONFLICT`` cursor upsert,
  * the ``hamming64`` baseline UDF driving vector nearest-neighbour,
  * and that the multi-db Alembic baseline builds the whole schema on Postgres.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest

from eyenet.contracts.audit import verify_chain
from eyenet.contracts.enums import FileServedVia, SensitivityTier
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository
from eyenet.storage.sqlmodel_repo.file_access import _PreparedJournalRow

pytestmark = pytest.mark.e2e

psycopg = pytest.importorskip("psycopg")

try:
    from testcontainers.postgres import PostgresContainer
except Exception:  # pragma: no cover — container lib optional
    PostgresContainer = None  # type: ignore[assignment,misc]


@pytest.fixture(scope="module")
def pg_container() -> Iterator[Any]:
    if PostgresContainer is None:
        pytest.skip("testcontainers not installed")
    try:
        with PostgresContainer("postgres:16-alpine") as container:
            yield container
    except Exception as exc:  # pragma: no cover — no docker in this environment
        pytest.skip(f"cannot start postgres container: {exc}")


@pytest.fixture
def pg_storage(pg_container: Any, monkeypatch: pytest.MonkeyPatch) -> Iterator[BaseRepository]:
    uid = uuid.uuid4().hex[:12]
    main_db = f"eyenet_{uid}"
    host = pg_container.get_container_host_ip()
    port = pg_container.get_exposed_port(5432)
    user = pg_container.username
    password = pg_container.password
    admin = (
        f"host={host} port={port} dbname={pg_container.dbname} "
        f"user={user} password={password}"
    )
    # The operator provisions both databases; the repo only builds their schema.
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{main_db}"')
        conn.execute(f'CREATE DATABASE "{main_db}_audit"')

    url = f"postgresql://{user}:{password}@{host}:{port}/{main_db}"
    monkeypatch.setenv("EYENET_STORAGE_TYPE", "postgres")
    storage = get_repository(url=url)  # runs the Postgres Alembic baseline on both DBs
    yield storage


def _audit_event(i: int) -> dict[str, Any]:
    return {
        "event": "evidence_access",
        "service": "engine",
        "instance_id": "eng_1",
        "subject_kind": "actor",
        "payload": {"i": i, "note": "smoke"},  # JSON column round-trip
        "at": datetime(2026, 5, 4, 12, i % 60, i // 60, tzinfo=UTC),
    }


@pytest.mark.asyncio
async def test_audit_chain_holds(pg_storage: BaseRepository) -> None:
    try:
        for i in range(25):
            await pg_storage.append_audit(_audit_event(i))
        rows = await pg_storage.all_audit()
        ok, broken = verify_chain(rows)
        assert ok and broken is None
        assert len(rows) == 25
        assert [r.payload["i"] for r in rows] == list(range(25))  # seq order preserved
    finally:
        await pg_storage.close()


def _prepared_row(seq_hint: int) -> _PreparedJournalRow:
    return _PreparedJournalRow(
        access_id=uuid.uuid4(),
        audit_event_id=None,
        user_id=uuid.uuid4(),
        grant_id=None,
        content_hash=bytes([seq_hint % 256]) * 32,
        content_size=100 + seq_hint,
        content_mime="application/pdf",
        tier=SensitivityTier.NORMAL,
        served_at=datetime(2026, 5, 4, 12, seq_hint, 0, tzinfo=UTC),
        served_via=next(iter(FileServedVia)),
        acknowledgment_id=None,
        operator_signature=bytes([1]) * 64,
        signing_pubkey_fingerprint="0123456789abcdef",
    )


@pytest.mark.asyncio
async def test_file_access_chain_holds(pg_storage: BaseRepository) -> None:
    try:
        ids = []
        for i in range(5):
            aid = await pg_storage._append_file_access_locked(
                _prepared_row(i), require_nonce=False, now=datetime.now(UTC)
            )
            ids.append(aid)
        assert len(set(ids)) == 5
        assert await pg_storage.verify_file_access_chain() is True
        # Head is the last-appended row's self_hash (non-genesis).
        head = await pg_storage.file_access_journal_head()
        assert head != b"\x00" * 32
    finally:
        await pg_storage.close()


@pytest.mark.asyncio
async def test_set_cursors_bulk_upsert(pg_storage: BaseRepository) -> None:
    try:
        actor = uuid.uuid4()
        msg1, msg2 = uuid.uuid4(), uuid.uuid4()
        ts = datetime(2026, 5, 4, 12, 0, 0, tzinfo=UTC)
        await pg_storage.set_cursors_bulk(actor, [("chatty_member", ts, msg1)])
        got = await pg_storage.get_cursors_bulk(actor, ["chatty_member"])
        assert got["chatty_member"][1] == msg1

        # ON CONFLICT DO UPDATE: same (actor, primitive) overwrites, no dup error.
        await pg_storage.set_cursors_bulk(actor, [("chatty_member", ts, msg2)])
        got = await pg_storage.get_cursors_bulk(actor, ["chatty_member"])
        assert got["chatty_member"][1] == msg2
    finally:
        await pg_storage.close()


@pytest.mark.asyncio
async def test_vector_nearest_uses_hamming64(pg_storage: BaseRepository) -> None:
    try:
        actor_a, actor_b = uuid.uuid4(), uuid.uuid4()
        await pg_storage.upsert_simhash(actor_a, "chatty_member", "0000000000000000")
        await pg_storage.upsert_simhash(actor_b, "chatty_member", "0000000000000003")  # 2 bits

        matches = await pg_storage.nearest_simhashes(
            "chatty_member", "0000000000000000", max_distance=4, exclude_actor_id=actor_a
        )
        dists = {m.distance for m in matches}
        assert 2 in dists  # hamming64(0x0, 0x3) == 2, the baseline UDF works
    finally:
        await pg_storage.close()
