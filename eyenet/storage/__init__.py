"""SQLite storage layer (DECNET-pattern flat repository).

Public surface:

  * :class:`BaseRepository` — flat ABC (~80 abstract methods)
  * :func:`get_repository` — env-dispatched factory
    (`EYENET_STORAGE_TYPE`, default `sqlite`)
  * `attachment_root` / `store_attachment` — blob-on-disk helpers
  * Error types — `CaseError`, `ClearanceGrantError`, `ReclassifyDemotionError`
  * `MAX_GRANT_DURATION` constant

The concrete SQLite implementation lives in :mod:`eyenet.storage.sqlite_repo`
and is reachable only through the factory. The per-domain mixins live in
:mod:`eyenet.storage.sqlmodel_repo` and are the shared generic layer that
future MySQL/Postgres backends will compose with their own overrides.
"""

from __future__ import annotations

from .attachments import attachment_root, store_attachment
from .errors import (
    MAX_GRANT_DURATION,
    CaseError,
    ClearanceGrantError,
    ReclassifyDemotionError,
)
from .factory import get_repository
from .repository import BaseRepository

__all__ = [
    "MAX_GRANT_DURATION",
    "BaseRepository",
    "CaseError",
    "ClearanceGrantError",
    "ReclassifyDemotionError",
    "attachment_root",
    "get_repository",
    "store_attachment",
]
