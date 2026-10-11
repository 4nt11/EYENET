# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Repository factory — selects a :class:`BaseRepository` implementation based on
``EYENET_STORAGE_TYPE`` (``sqlite`` default; ``postgres`` for high-ingest prod;
``mysql`` when that backend lands).
"""

import inspect
import os
from typing import Any

from eyenet.storage.repository import BaseRepository


def _accepted(cls: type, kwargs: dict[str, Any]) -> dict[str, Any]:
    """Keep only kwargs the backend's ``__init__`` declares.

    Callers pass backend-agnostic kwargs (the CLI always passes SQLite's
    ``data_dir``); each backend takes the subset it understands and reads the
    rest from the environment (Postgres: ``EYENET_PG_URL`` / ``EYENET_PG_DDL_URL``).
    This keeps the factory the single dispatch point without every caller
    branching on ``EYENET_STORAGE_TYPE``.
    """
    params = inspect.signature(cls).parameters
    return {k: v for k, v in kwargs.items() if k in params}


def get_repository(**kwargs: Any) -> BaseRepository:
    """Instantiate the repository implementation selected by ``EYENET_STORAGE_TYPE``.

    Kwargs are filtered to those the chosen backend accepts (see ``_accepted``):

    * SQLite accepts ``data_dir``, ``in_memory``, ``ndjson_path``.
    * Postgres accepts ``url`` / ``audit_url`` / ``ddl_url`` and pool knobs, and
      falls back to ``EYENET_PG_URL`` / ``EYENET_PG_DDL_URL`` from the env.
    * MySQL (future) accepts ``url`` and engine tuning knobs.
    """
    db_type = os.environ.get("EYENET_STORAGE_TYPE", "sqlite").lower()

    if db_type == "sqlite":
        from eyenet.storage.sqlite_repo.repository import SQLiteRepository  # noqa: PLC0415

        return SQLiteRepository(**_accepted(SQLiteRepository, kwargs))
    if db_type == "postgres":  # pragma: no cover — needs a live Postgres (e2e only)
        from eyenet.storage.postgres_repo.repository import PostgresRepository  # noqa: PLC0415

        return PostgresRepository(**_accepted(PostgresRepository, kwargs))
    raise ValueError(f"Unsupported database type: {db_type}")


__all__ = ["get_repository"]
