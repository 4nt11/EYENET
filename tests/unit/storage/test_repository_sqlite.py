"""SQLite-pinned: storage layer engine + pragma probes.

Per [[feedback_use_baserepo_abstraction_in_tests]], goes through
``get_repository`` with ``EYENET_STORAGE_TYPE=sqlite``. The filename
suffix signals the dialect.

API_PLAN §9.4 — the 8-engine layout was collapsed to 2 physical SQLite
files (``main.db`` + ``audit.db``) at M9.1a.2a. This test probes the
two-engine boot path on disk.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text

from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository


@pytest.fixture
def storage(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> BaseRepository:
    monkeypatch.setenv("EYENET_STORAGE_TYPE", "sqlite")
    return get_repository(data_dir=tmp_path)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_open_close(storage: BaseRepository, tmp_path: Path) -> None:
    try:
        assert (tmp_path / "main.db").exists()
        assert (tmp_path / "audit.db").exists()
    finally:
        await storage.close()


@pytest.mark.unit
def test_pragmas_applied(storage: BaseRepository) -> None:
    engine = storage.sync_engine  # type: ignore[attr-defined]
    with engine.connect() as conn:
        fk = conn.execute(text("PRAGMA foreign_keys")).scalar()
        jm = conn.execute(text("PRAGMA journal_mode")).scalar()
        sync = conn.execute(text("PRAGMA synchronous")).scalar()
    assert fk == 1
    assert jm == "wal"
    assert sync == 1  # NORMAL


@pytest.mark.unit
def test_audit_isolated_from_main(storage: BaseRepository) -> None:
    audit_engine = storage.audit_sync_engine  # type: ignore[attr-defined]
    main_engine = storage.sync_engine  # type: ignore[attr-defined]

    with audit_engine.connect() as conn:
        audit_tables = {
            row[0]
            for row in conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            ).fetchall()
        }
    assert "audit_log" in audit_tables
    assert "message" not in audit_tables

    with main_engine.connect() as conn:
        main_tables = {
            row[0]
            for row in conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            ).fetchall()
        }
    assert {"profile", "linkage", "persona", "persona_membership"} <= main_tables
