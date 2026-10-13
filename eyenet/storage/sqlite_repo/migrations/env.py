# SPDX-License-Identifier: AGPL-3.0-or-later
"""Alembic environment — multi-database (main.db + audit.db), one tree.

Two logical databases share this single migration history. Each physical file
keeps its OWN ``alembic_version`` table, so their heads advance independently
even though the revision graph is linear and shared. A revision carries an
``upgrade_main`` / ``upgrade_audit`` pair; this env runs the migration once per
engine, dispatching to the half that matches.

Engines come from one of two places:

  * **Programmatic** (the app boot path, :func:`...database.upgrade_to_head`):
    the two engines are injected via ``config.attributes["engines"]``. This is
    what makes in-memory (shared-cache ``StaticPool``) DBs migratable — there is
    no URL to put in ``alembic.ini`` for a per-process ``:memory:`` cache.
  * **CLI** (``alembic revision --autogenerate`` during development): built here
    from ``-x data_dir=<path>`` (default ``./data``).

Raw DDL that lives outside ``SQLModel.metadata`` (the FTS5 index + its shadow
tables, ``vector_signature``, the partial UNIQUE index) is excluded from
autogenerate via ``include_name`` so a future ``--autogenerate`` never emits a
DROP for schema it cannot see in the models.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from alembic import context
from sqlmodel import SQLModel

import eyenet.models  # noqa: F401 — registers every table on SQLModel.metadata
from eyenet.storage.sqlite_repo.database import (
    _AUDIT_TABLES,
    _MAIN_TABLES,
    _RAW_DDL_OBJECTS,
    _sqlite_compare_type,
    get_sync_engine,
)

config = context.config
target_metadata = SQLModel.metadata

# Logical DB name -> the frozenset of table names that belong in that file.
_SUBSETS: dict[str, frozenset[str]] = {"main": _MAIN_TABLES, "audit": _AUDIT_TABLES}


def _engines() -> dict[str, object]:
    injected = config.attributes.get("engines")
    if injected is not None:
        return injected
    x_args = context.get_x_argument(as_dictionary=True)
    data_dir = Path(x_args.get("data_dir", "data"))
    return {
        "main": get_sync_engine(data_dir / "main.db"),
        "audit": get_sync_engine(data_dir / "audit.db"),
    }


def _make_include_name(
    subset: frozenset[str],
) -> Callable[[str | None, str, dict[str, str | None]], bool]:
    """Filter names read FROM the database during reflection (drops FTS shadows)."""

    def include_name(name: str | None, type_: str, parent_names: dict[str, str | None]) -> bool:
        if name in _RAW_DDL_OBJECTS:
            return False
        if type_ == "table":
            return name is None or name in subset
        return True

    return include_name


def _make_include_object(
    subset: frozenset[str],
) -> Callable[[object, str | None, str, bool, object], bool]:
    """Filter objects on BOTH sides of the diff — this is what keeps the other
    DB's metadata tables (all 64 live on one ``SQLModel.metadata``) from being
    proposed as ``add_table`` against the wrong file, and keeps the raw-DDL
    objects from being proposed as ``drop``."""

    def include_object(
        obj: object, name: str | None, type_: str, reflected: bool, compare_to: object
    ) -> bool:
        if name in _RAW_DDL_OBJECTS:
            return False
        if type_ == "table":
            return name in subset
        return True

    return include_object


def run_migrations_online() -> None:
    for name, engine in _engines().items():
        with engine.connect() as connection:  # type: ignore[attr-defined]
            # SQLite enforces FK on DROP TABLE, which breaks the batch table-rewrite
            # (copy → DROP old → RENAME) for any table with INBOUND FKs — e.g.
            # group_candidate, referenced by membership / access_artifact /
            # group_candidate_mention (migration 0009). Disable FK enforcement for
            # the MIGRATION connection only, set on the raw DBAPI connection BEFORE
            # any transaction (SQLite silently ignores this pragma inside a txn).
            # Runtime engines keep foreign_keys=ON. We do NOT run a global
            # foreign_key_check afterwards: the live corpus already carries
            # pre-existing orphans (retention deletes without cascade), so a global
            # check would conflate that debt with migration correctness and brick
            # every deploy. A batch rewrite preserves the rewritten table's ids, so
            # inbound FKs stay valid; verify the specific change on a DB copy.
            raw = connection.connection
            pre = raw.cursor()
            prev_fk = pre.execute("PRAGMA foreign_keys").fetchone()[0]
            pre.execute("PRAGMA foreign_keys=OFF")
            pre.close()
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                render_as_batch=True,  # SQLite cannot ALTER in place; batch = copy-and-move
                include_name=_make_include_name(_SUBSETS[name]),
                include_object=_make_include_object(_SUBSETS[name]),
                include_schemas=False,
                transaction_per_migration=True,
                compare_type=_sqlite_compare_type,
                # Route autogenerated diffs into the per-engine upgrade_<name>/
                # downgrade_<name> halves of the revision template.
                upgrade_token=f"{name}_upgrades",
                downgrade_token=f"{name}_downgrades",
            )
            with context.begin_transaction():
                context.run_migrations(engine_name=name)
            # Restore the connection's prior FK setting before it returns to the
            # pool — SQLite pools reuse connections, and the connect-event pragma
            # only fires on NEW physical connections. Without this the migration's
            # FK=OFF would leak into runtime use of a reused connection.
            post = connection.connection.cursor()
            post.execute(f"PRAGMA foreign_keys={'ON' if prev_fk else 'OFF'}")
            post.close()


if context.is_offline_mode():  # pragma: no cover — EYENET never uses --sql offline mode
    raise NotImplementedError("EYENET runs Alembic online only (no --sql offline mode)")
run_migrations_online()
