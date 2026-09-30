# SPDX-License-Identifier: AGPL-3.0-or-later
"""0003 seq migration — the existing-DB (live cutover) branch, SQLite-pinned.

The fresh-DB path is covered by the baseline equivalence test (0003 is a no-op
there because create_all already builds ``seq``). This pins the OTHER branch:
a DB stamped at an earlier revision, holding real chain rows, gets ``seq`` added
AND backfilled in insertion order on the next upgrade — the operating-DB path,
which is tamper-chain-critical (a wrong backfill order silently breaks the
chain walk). We simulate "pre-seq" by downgrading past 0003.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import text

from eyenet.contracts.audit import verify_chain
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository
from eyenet.storage.sqlite_repo.database import _MIGRATIONS_DIR


@pytest.fixture
def storage(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> BaseRepository:
    monkeypatch.setenv("EYENET_STORAGE_TYPE", "sqlite")
    return get_repository(data_dir=tmp_path)


def _run(cmd: str, main_engine: object, audit_engine: object, target: str) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
    cfg.attributes["engines"] = {"main": main_engine, "audit": audit_engine}
    getattr(command, cmd)(cfg, target)


def _audit_cols(engine: object) -> set[str]:
    with engine.connect() as c:  # type: ignore[attr-defined]
        rows = c.execute(text("PRAGMA table_info(audit_log)")).all()
    return {r[1] for r in rows}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_0003_backfills_seq_on_existing_db(storage: BaseRepository) -> None:
    try:
        # Real chain rows, appended in a known order.
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

        # Simulate a pre-seq operating DB: roll the audit chain back past 0003.
        _run("downgrade", storage.sync_engine, storage.audit_sync_engine, "0002_forum_crawl_cursor")
        assert "seq" not in _audit_cols(storage.audit_sync_engine)

        # The next deploy: 0003 adds seq + backfills from rowid (insertion order).
        _run("upgrade", storage.sync_engine, storage.audit_sync_engine, "head")
        assert "seq" in _audit_cols(storage.audit_sync_engine)

        with storage.audit_sync_engine.connect() as c:  # type: ignore[attr-defined]
            seqs = c.execute(text("SELECT seq FROM audit_log ORDER BY seq")).scalars().all()
        # Contiguous, 1-based, one per row — exact insertion order preserved.
        assert seqs == [1, 2, 3, 4, 5]

        # And the chain still verifies when walked by the new seq order.
        rows = await storage.all_audit()
        ok, broken = verify_chain(rows)
        assert ok and broken is None
        assert len(rows) == 5
    finally:
        await storage.close()
