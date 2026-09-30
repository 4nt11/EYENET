# SPDX-License-Identifier: AGPL-3.0-or-later
"""Alembic baseline — SQLite-impl probe (v0.1.0 cutover).

Pins ``EYENET_STORAGE_TYPE=sqlite`` and carries the ``_sqlite`` suffix because
it inspects backend-specific artifacts (per-file ``alembic_version`` tables, the
raw FTS5/vector_signature/partial-index DDL, the multi-DB routing). A future
MySQL/Postgres backend gets its own mirror alongside.

Guards the three things the cutover can silently get wrong:
  1. the migrated schema is COMPLETE and ROUTED (no table in the wrong DB);
  2. the models do not DRIFT from the baseline (empty autogenerate diff) — i.e.
     ``upgrade head`` == the legacy ``create_all`` output;
  3. ``downgrade base`` is clean.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import text
from sqlmodel import SQLModel

import eyenet.models  # noqa: F401 — populate metadata
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository
from eyenet.storage.sqlite_repo.database import (
    _AUDIT_TABLES,
    _MAIN_TABLES,
    _MIGRATIONS_DIR,
    _RAW_DDL_OBJECTS,
    _sqlite_compare_type,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def storage(monkeypatch: pytest.MonkeyPatch) -> BaseRepository:
    monkeypatch.setenv("EYENET_STORAGE_TYPE", "sqlite")
    return get_repository(in_memory=True)


def _head_revision() -> str:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config()
    cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
    return ScriptDirectory.from_config(cfg).get_current_head()


def _objects(engine: object) -> dict[str, str]:
    with engine.connect() as c:  # type: ignore[attr-defined]
        rows = c.execute(
            text("select type, name from sqlite_master where name not like 'sqlite_%'")
        ).all()
    return {r[1]: r[0] for r in rows}


def test_schema_complete_and_routed(storage: BaseRepository) -> None:
    main = _objects(storage.sync_engine)
    audit = _objects(storage.audit_sync_engine)

    # every ORM table present in the right file
    assert not [t for t in _MAIN_TABLES if t not in main]
    assert not [t for t in _AUDIT_TABLES if t not in audit]

    # the raw DDL the models can't express
    for name in ("vector_signature", "ix_vs_primitive", "message_fts"):
        assert name in main
    assert {"message_fts_ai", "message_fts_ad", "message_fts_au"} <= set(main)
    assert "uq_signing_pubkey_active" in audit

    # NO cross-DB leakage (the multi-db include_object filter working)
    assert not [t for t in _AUDIT_TABLES if t in main]
    assert not [t for t in _MAIN_TABLES if t in audit]

    # both files migrated to the current head (0001 + any later revisions)
    head = _head_revision()
    for engine in (storage.sync_engine, storage.audit_sync_engine):
        with engine.connect() as c:
            stamped = c.execute(text("select version_num from alembic_version")).scalar()
        assert stamped == head


def _drift(engine: object, subset: frozenset[str]) -> list[object]:
    def include_name(name: str | None, type_: str, parent: dict[str, str | None]) -> bool:
        if name in _RAW_DDL_OBJECTS:
            return False
        if type_ == "table":
            return name is None or name in subset
        return True

    def include_object(
        obj: object, name: str | None, type_: str, reflected: bool, compare_to: object
    ) -> bool:
        if name in _RAW_DDL_OBJECTS:
            return False
        if type_ == "table":
            return name in subset
        return True

    with engine.connect() as conn:  # type: ignore[attr-defined]
        mc = MigrationContext.configure(
            conn,
            opts={
                "target_metadata": SQLModel.metadata,
                "include_name": include_name,
                "include_object": include_object,
                "compare_type": _sqlite_compare_type,
                "include_schemas": False,
            },
        )
        return compare_metadata(mc, SQLModel.metadata)


def test_no_model_drift_from_baseline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("EYENET_STORAGE_TYPE", "sqlite")
    repo = get_repository(data_dir=tmp_path)
    assert _drift(repo.sync_engine, _MAIN_TABLES) == []
    assert _drift(repo.audit_sync_engine, _AUDIT_TABLES) == []


def _run(cmd: str, main_engine: object, audit_engine: object, target: str) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
    cfg.attributes["engines"] = {"main": main_engine, "audit": audit_engine}
    getattr(command, cmd)(cfg, target)


def test_downgrade_base_is_clean(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("EYENET_STORAGE_TYPE", "sqlite")
    repo = get_repository(data_dir=tmp_path)
    _run("downgrade", repo.sync_engine, repo.audit_sync_engine, "base")

    for engine, subset, raw in (
        (repo.sync_engine, _MAIN_TABLES, {"vector_signature", "message_fts"}),
        (repo.audit_sync_engine, _AUDIT_TABLES, set()),
    ):
        remaining = _objects(engine)
        assert not [t for t in subset if t in remaining], f"ORM tables survived: {remaining}"
        assert not [t for t in raw if t in remaining], f"raw DDL survived: {remaining}"
        # only alembic's own bookkeeping table is allowed to remain
        assert set(remaining) <= {"alembic_version"}


def test_incremental_0002_adds_forum_crawl_cursor(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The operating-DB path: a DB at 0001 gets forum_crawl_cursor via 0002 on
    the next upgrade (not a fresh build). This is what the live stamped DB does
    on its next deploy."""
    monkeypatch.setenv("EYENET_STORAGE_TYPE", "sqlite")
    repo = get_repository(data_dir=tmp_path)  # boots to head

    # roll back to the frozen baseline: forum_crawl_cursor must disappear
    _run("downgrade", repo.sync_engine, repo.audit_sync_engine, "0001_baseline")
    with repo.sync_engine.connect() as c:  # type: ignore[attr-defined]
        assert (
            c.execute(text("select version_num from alembic_version")).scalar() == "0001_baseline"
        )
    assert "forum_crawl_cursor" not in _objects(repo.sync_engine)

    # upgrade one step: 0002 creates it
    _run("upgrade", repo.sync_engine, repo.audit_sync_engine, "head")
    assert "forum_crawl_cursor" in _objects(repo.sync_engine)
    assert _drift(repo.sync_engine, _MAIN_TABLES) == []
