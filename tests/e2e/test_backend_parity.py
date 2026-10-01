# SPDX-License-Identifier: AGPL-3.0-or-later
"""Cross-backend parity — SQLite vs Postgres produce identical behavior.

The drift tripwire. Runs the SAME battery through both concrete backends and
asserts the observable results match. It targets the surfaces the two backends
implement DIFFERENTLY (the advisory-lock vs BEGIN IMMEDIATE audit chain, the
ON CONFLICT cursor upsert, the hamming64 vector search) so a future change that
silently diverges one backend fails here.

``self_hash``/``id`` are intentionally NOT compared: the row ``id`` is a
per-append uuid7 (differs across runs), so the hashes differ. Parity is "same
logical content + each chain independently verifies", which is the property that
actually matters.
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
from eyenet.storage.repository import BaseRepository

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(180)]

psycopg = pytest.importorskip("psycopg")

try:
    from testcontainers.postgres import PostgresContainer
except Exception:  # pragma: no cover
    PostgresContainer = None  # type: ignore[assignment,misc]

# Fixed inputs so the comparable outputs (cursor msg_id, vector keys) match
# across the two independently-seeded backends.
_ACTOR = uuid.UUID("06ab0000-0000-7000-8000-000000000001")
_MSG = uuid.UUID("06ab0000-0000-7000-8000-000000000002")
_TS = datetime(2026, 5, 4, 9, 0, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def pg_container() -> Iterator[Any]:
    if PostgresContainer is None:
        pytest.skip("testcontainers not installed")
    try:
        with PostgresContainer("postgres:16-alpine") as container:
            yield container
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"cannot start postgres container: {exc}")


async def _battery(repo: BaseRepository) -> dict[str, Any]:
    """Run the same operations and return a backend-agnostic result view."""
    for i in range(6):
        await repo.append_audit(
            {
                "event": "evidence_access",
                "service": "engine",
                "instance_id": "eng_1",
                "subject_kind": "actor",
                "payload": {"i": i, "tag": "parity"},
                "at": datetime(2026, 5, 4, 12, i, 0, tzinfo=UTC),
            }
        )
    rows = await repo.all_audit()
    ok, broken = verify_chain(rows)

    # ON CONFLICT upsert: set, then overwrite the same key.
    await repo.set_cursors_bulk(_ACTOR, [("chatty_member", _TS, uuid.uuid4())])
    await repo.set_cursors_bulk(_ACTOR, [("chatty_member", _TS, _MSG)])
    cursor = (await repo.get_cursors_bulk(_ACTOR, ["chatty_member"]))["chatty_member"]

    # hamming64 nearest-neighbour.
    await repo.upsert_simhash(_ACTOR, "chatty_member", "0000000000000000")
    other = uuid.UUID("06ab0000-0000-7000-8000-000000000003")
    await repo.upsert_simhash(other, "chatty_member", "0000000000000007")  # 3 bits
    matches = await repo.nearest_simhashes(
        "chatty_member", "0000000000000000", max_distance=8, exclude_actor_id=_ACTOR
    )

    return {
        "audit_count": len(rows),
        "audit_valid": ok and broken is None,
        "audit_events": [(r.event, r.payload["i"], r.payload["tag"]) for r in rows],
        "cursor_msg_id": cursor[1],
        "vector_distances": sorted(m.distance for m in matches),
    }


@pytest.mark.asyncio
async def test_sqlite_postgres_parity(
    pg_container: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EYENET_STORAGE_TYPE", "sqlite")
    sqlite_repo = get_repository(data_dir=tmp_path)

    host, port = pg_container.get_container_host_ip(), pg_container.get_exposed_port(5432)
    user, password = pg_container.username, pg_container.password
    admin = f"host={host} port={port} dbname={pg_container.dbname} user={user} password={password}"
    db = f"eyenet_parity_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{db}"')
        conn.execute(f'CREATE DATABASE "{db}_audit"')
    url = f"postgresql://{user}:{password}@{host}:{port}/{db}"
    monkeypatch.setenv("EYENET_STORAGE_TYPE", "postgres")
    pg_repo = get_repository(url=url)

    try:
        sqlite_result = await _battery(sqlite_repo)
        pg_result = await _battery(pg_repo)
        assert sqlite_result["audit_valid"] is True
        assert pg_result["audit_valid"] is True
        assert sqlite_result == pg_result, (
            f"backend drift:\n sqlite={sqlite_result}\n pg={pg_result}"
        )
    finally:
        await sqlite_repo.close()
        await pg_repo.close()
