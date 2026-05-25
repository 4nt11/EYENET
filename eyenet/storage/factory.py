# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Repository factory — selects a :class:`BaseRepository` implementation based on
``EYENET_STORAGE_TYPE`` (currently only ``sqlite``; ``mysql`` / ``postgres``
land when those backends do).
"""

from __future__ import annotations

import os
from typing import Any

from eyenet.storage.repository import BaseRepository


def get_repository(**kwargs: Any) -> BaseRepository:
    """Instantiate the repository implementation selected by ``EYENET_STORAGE_TYPE``.

    Keyword arguments are forwarded to the concrete implementation:

    * SQLite accepts ``data_dir``, ``in_memory``, ``ndjson_path``.
    * MySQL / Postgres (future) accept ``url`` and engine tuning knobs.
    """
    db_type = os.environ.get("EYENET_STORAGE_TYPE", "sqlite").lower()

    if db_type == "sqlite":
        from eyenet.storage.sqlite_repo.repository import SQLiteRepository  # noqa: PLC0415

        return SQLiteRepository(**kwargs)
    raise ValueError(f"Unsupported database type: {db_type}")


__all__ = ["get_repository"]
