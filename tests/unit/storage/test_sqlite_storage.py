"""Storage layer: per-store engines open/close, pragmas active."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text

from eyenet.storage import SQLiteStorage, StoreName, open_all


@pytest.mark.unit
@pytest.mark.asyncio
async def test_open_close(tmp_path: Path) -> None:
    s = SQLiteStorage(tmp_path)
    try:
        for name in StoreName:
            assert (tmp_path / f"{name.value}.db").exists()
    finally:
        await s.close()


@pytest.mark.unit
def test_pragmas_applied(tmp_path: Path) -> None:
    engines = open_all(tmp_path)
    try:
        engine = engines[StoreName.MAIN]
        with engine.connect() as conn:
            fk = conn.execute(text("PRAGMA foreign_keys")).scalar()
            jm = conn.execute(text("PRAGMA journal_mode")).scalar()
            sync = conn.execute(text("PRAGMA synchronous")).scalar()
        assert fk == 1
        assert jm == "wal"
        assert sync == 1  # NORMAL
    finally:
        for e in engines.values():
            e.dispose()


@pytest.mark.unit
def test_each_store_has_only_its_tables(tmp_path: Path) -> None:
    engines = open_all(tmp_path)
    try:
        # Audit DB has audit_log and nothing else.
        with engines[StoreName.AUDIT].connect() as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table'")
                ).fetchall()
            }
        assert "audit_log" in tables
        assert "message" not in tables
        # Profiles DB has linkage / persona / persona_membership.
        with engines[StoreName.MAIN].connect() as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table'")
                ).fetchall()
            }
        assert {"profile", "linkage", "persona", "persona_membership"} <= tables
    finally:
        for e in engines.values():
            e.dispose()
