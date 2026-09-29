"""End-to-end audit chain test — SQLite-pinned (BEGIN IMMEDIATE path).

Probes the dialect-specific hash-chained append on the SQLite backend.
Per [[feedback_use_baserepo_abstraction_in_tests]], even SQLite-specific
probes go through the factory; the env var pins the backend and the
filename (``_sqlite`` suffix) signals the scope.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest

from eyenet.contracts.audit import verify_chain
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository


@pytest.fixture
def storage(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> BaseRepository:
    monkeypatch.setenv("EYENET_STORAGE_TYPE", "sqlite")
    return get_repository(data_dir=tmp_path)


@pytest.fixture
def storage_with_ndjson(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> BaseRepository:
    monkeypatch.setenv("EYENET_STORAGE_TYPE", "sqlite")
    return get_repository(data_dir=tmp_path, ndjson_path=tmp_path / "audit.ndjson")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_chain_holds_over_100_events(storage: BaseRepository) -> None:
    try:
        for i in range(100):
            await storage.append_audit(
                {
                    "event": "evidence_access",
                    "service": "engine",
                    "instance_id": "eng_1",
                    "subject_kind": "actor",
                    "at": datetime(2026, 5, 4, 12, i % 60, i // 60, tzinfo=UTC),
                }
            )
        rows = await storage.all_audit()
        ok, broken = verify_chain(rows)
        assert ok
        assert broken is None
        assert len(rows) == 100
    finally:
        await storage.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_append_does_not_leak_greenlet(
    storage: BaseRepository, caplog: pytest.LogCaptureFixture
) -> None:
    """Regression: the audit append released its raw connection with a SYNC
    ``raw_conn.close()``, which fired ``MissingGreenlet`` on the aiosqlite pool's
    reset-on-return rollback (SQLAlchemy catches + logs it, so the row still
    persisted but every write churned a connection and logged a traceback — 37k
    on the linker in production). The async ``connect()`` release runs the reset
    in-greenlet.

    Only reproduces on a FILE-backed engine (a real pool); the in-memory
    ``StaticPool`` never returns/reset the connection, which is why the unit
    suite missed it — hence the ``_sqlite`` file fixture (``data_dir=tmp_path``).
    """
    try:
        with caplog.at_level(logging.DEBUG, logger="sqlalchemy"):
            for i in range(5):
                await storage.append_audit(
                    {
                        "event": "evidence_access",
                        "service": "engine",
                        "instance_id": "eng_1",
                        "subject_kind": "actor",
                        "at": datetime(2026, 5, 4, 12, i, 0, tzinfo=UTC),
                    }
                )
        blob = caplog.text
        assert "MissingGreenlet" not in blob, "audit append leaked a greenlet on conn reset"
        assert "greenlet_spawn has not been called" not in blob
    finally:
        await storage.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ndjson_mirror(storage_with_ndjson: BaseRepository, tmp_path: Path) -> None:
    try:
        await storage_with_ndjson.append_audit(
            {
                "event": "service.start",
                "service": "engine",
                "instance_id": "eng_1",
                "subject_kind": "service",
                "at": datetime(2026, 5, 4, 12, 0, 0, tzinfo=UTC),
            }
        )
    finally:
        await storage_with_ndjson.close()
    ndjson = tmp_path / "audit.ndjson"
    assert ndjson.exists()
    assert ndjson.stat().st_mode & 0o777 == 0o600
    content = ndjson.read_text("utf-8").strip().splitlines()
    assert len(content) == 1
