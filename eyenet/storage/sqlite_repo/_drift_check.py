# SPDX-License-Identifier: AGPL-3.0-or-later
"""Ops tool: report Alembic autogenerate drift between the models and a live DB.

Used by the cutover runbook (`development/alembic-cutover-runbook.md`) to prove a
populated DB matches the ``0001_baseline`` schema BEFORE stamping it — a stamp
over a mismatch would lie. Exits non-zero if either DB drifts.

    python -m eyenet.storage.sqlite_repo._drift_check <data_dir>
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import cast

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlmodel import SQLModel

import eyenet.models  # noqa: F401 — populate metadata
from eyenet.storage.sqlite_repo.database import (
    _AUDIT_TABLES,
    _MAIN_TABLES,
    _RAW_DDL_OBJECTS,
    get_sync_engine,
)


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
                "compare_type": True,
                "include_schemas": False,
            },
        )
        return cast("list[object]", compare_metadata(mc, SQLModel.metadata))


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m eyenet.storage.sqlite_repo._drift_check <data_dir>")
        return 2
    data_dir = Path(argv[1])
    drifted = False
    for label, db, subset in (
        ("main", "main.db", _MAIN_TABLES),
        ("audit", "audit.db", _AUDIT_TABLES),
    ):
        diffs = _drift(get_sync_engine(data_dir / db), subset)
        print(f"{label} drift: {len(diffs)}")
        for d in diffs:
            print(f"  {d}")
        drifted = drifted or bool(diffs)
    if drifted:
        print("DRIFT DETECTED — resolve before stamping (see runbook step 4).")
        return 1
    print("no drift — safe to `alembic stamp 0001_baseline`.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
