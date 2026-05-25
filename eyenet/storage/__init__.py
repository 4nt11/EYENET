"""SQLite storage layer.

This package is mid-restructure. Two surfaces coexist for now:

  * **Legacy** (pre-restructure): the flat per-domain modules below
    (``actors``, ``audit``, ``cursors``, ..., ``sqlite.SQLiteStorage``)
    and the sub-store ABCs in :mod:`eyenet.contracts.storage`. All
    current callers still target this surface.
  * **New** (DECNET pattern): :class:`BaseRepository` flat ABC in
    :mod:`eyenet.storage.repository` with one concrete impl in
    :mod:`eyenet.storage.sqlite_repo`, dispatched via
    :func:`get_repository`. Caller migration happens in a follow-up.

The new surface is additive — the legacy exports below remain so
existing imports keep working until the caller sweep lands.
"""

from __future__ import annotations

from .actors import resolve_actor_id, upsert_actor, upsert_group, upsert_source
from .attachments import attachment_root, store_attachment
from .audit import SQLiteAuditStore
from .cursors import SQLiteCursorStore
from .engines import StoreName, open_all, open_engine, open_in_memory_engine
from .errors import (
    MAX_GRANT_DURATION,
    CaseError,
    ClearanceGrantError,
    ReclassifyDemotionError,
)
from .factory import get_repository
from .feedback import SQLiteFeedbackPairStore
from .linkages import SQLiteLinkageStore
from .personas import SQLitePersonaStore
from .reply_resolver import resolve_message_id
from .repository import BaseRepository
from .sqlite import SQLiteStorage
from .syslog import SQLiteSystemLogStore
from .vectors import SQLiteVectorIndex, VectorMatch

__all__ = [
    "MAX_GRANT_DURATION",
    "BaseRepository",
    "CaseError",
    "ClearanceGrantError",
    "ReclassifyDemotionError",
    "SQLiteAuditStore",
    "SQLiteCursorStore",
    "SQLiteFeedbackPairStore",
    "SQLiteLinkageStore",
    "SQLitePersonaStore",
    "SQLiteStorage",
    "SQLiteSystemLogStore",
    "SQLiteVectorIndex",
    "StoreName",
    "VectorMatch",
    "attachment_root",
    "get_repository",
    "open_all",
    "open_engine",
    "open_in_memory_engine",
    "resolve_actor_id",
    "resolve_message_id",
    "store_attachment",
    "upsert_actor",
    "upsert_group",
    "upsert_source",
]
