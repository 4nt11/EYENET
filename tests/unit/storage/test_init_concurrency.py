"""Cross-process schema-init must not race on an empty data_dir.

Two `eyenet` processes booting against the same fresh `data_dir` used to
collide on `CREATE TABLE system_user` because SQLAlchemy's
`create_all(checkfirst=True)` separates the existence check from the DDL.
The `_init_lock` POSIX flock in `engines.py` serializes the init window so
the second process sees fully-populated metadata and `checkfirst` no-ops.
"""

from __future__ import annotations

import multiprocessing as mp
import sqlite3
from pathlib import Path

import pytest

from eyenet.storage.engines import StoreName


def _init_worker(data_dir: str) -> str:
    # Subprocess entry point — keep imports inside so each spawned interpreter
    # pays them once (mirrors a real `eyenet linker` boot).
    from eyenet.storage import SQLiteStorage

    try:
        SQLiteStorage(Path(data_dir))
    except Exception as exc:  # pragma: no cover — diagnostic on failure only
        return f"FAIL: {type(exc).__name__}: {exc}"
    return "OK"


@pytest.mark.unit
def test_four_processes_init_same_empty_data_dir(tmp_path: Path) -> None:
    ctx = mp.get_context("spawn")
    with ctx.Pool(processes=4) as pool:
        results = pool.map(_init_worker, [str(tmp_path)] * 4)

    assert results == ["OK"] * 4, f"some workers failed: {results}"

    # Every per-store DB file should exist.
    for store in StoreName:
        assert (tmp_path / f"{store.value}.db").exists()

    # And a sentinel table — audit_log, which exists across the smoke regression — is present.
    with sqlite3.connect(tmp_path / "audit.db") as conn:
        names = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert "audit_log" in names
