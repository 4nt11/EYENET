"""End-to-end audit chain test — SQLite-pinned (BEGIN IMMEDIATE path).

Probes the dialect-specific hash-chained append on the SQLite backend.
Per [[feedback_use_baserepo_abstraction_in_tests]], even SQLite-specific
probes go through the factory; the env var pins the backend and the
filename (``_sqlite`` suffix) signals the scope.
"""

from __future__ import annotations

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
