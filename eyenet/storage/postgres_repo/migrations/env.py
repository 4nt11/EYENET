# SPDX-License-Identifier: AGPL-3.0-or-later
"""Alembic environment — multi-database (main + audit), Postgres, one tree.

The Postgres mirror of the SQLite backend's env. Two logical databases share one
linear revision history; each keeps its own ``alembic_version``. A revision
carries ``upgrade_main`` / ``upgrade_audit`` halves; this env runs the migration
once per engine, dispatching to the matching half.

Differences from the SQLite env: ``render_as_batch=False`` (Postgres does real
in-place ALTER) and no ``compare_type`` shim (Postgres enforces real types).

Engines come from ``config.attributes["engines"]`` (the app boot path) or, for
the ``alembic`` CLI, from ``-x main_url=...`` (audit derived as ``<db>_audit``).

The table-routing sets (which model table lives in which physical DB) are
dialect-neutral, so they are reused from the SQLite backend module.
# ponytail: reuse, not duplicate. Graduate them to a shared storage module the
# day a THIRD backend lands; two is not yet worth the move.
"""

from __future__ import annotations

from collections.abc import Callable

from alembic import context
from sqlmodel import SQLModel

import eyenet.models  # noqa: F401 — registers every table on SQLModel.metadata
from eyenet.storage.postgres_repo.database import (
    _RAW_DDL_OBJECTS,
    audit_url_for,
    get_sync_engine,
)
from eyenet.storage.sqlite_repo.database import _AUDIT_TABLES, _MAIN_TABLES

config = context.config
target_metadata = SQLModel.metadata

_SUBSETS: dict[str, frozenset[str]] = {"main": _MAIN_TABLES, "audit": _AUDIT_TABLES}


def _engines() -> dict[str, object]:
    injected = config.attributes.get("engines")
    if injected is not None:
        return injected
    x_args = context.get_x_argument(as_dictionary=True)
    main_url = x_args["main_url"]
    return {
        "main": get_sync_engine(main_url),
        "audit": get_sync_engine(audit_url_for(main_url)),
    }


def _make_include_name(
    subset: frozenset[str],
) -> Callable[[str | None, str, dict[str, str | None]], bool]:
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
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                render_as_batch=False,  # Postgres alters in place
                include_name=_make_include_name(_SUBSETS[name]),
                include_object=_make_include_object(_SUBSETS[name]),
                include_schemas=False,
                transaction_per_migration=True,
                upgrade_token=f"{name}_upgrades",
                downgrade_token=f"{name}_downgrades",
            )
            with context.begin_transaction():
                context.run_migrations(engine_name=name)


if context.is_offline_mode():  # pragma: no cover — EYENET runs Alembic online only
    raise NotImplementedError("EYENET runs Alembic online only (no --sql offline mode)")
run_migrations_online()
