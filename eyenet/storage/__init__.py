"""SQLite storage layer."""

from __future__ import annotations

from .actors import resolve_actor_id, upsert_actor, upsert_group, upsert_source
from .attachments import attachment_root, store_attachment
from .audit import SQLiteAuditStore
from .cursors import SQLiteCursorStore
from .engines import StoreName, open_all, open_engine, open_in_memory_engine
from .feedback import SQLiteFeedbackPairStore
from .linkages import SQLiteLinkageStore
from .personas import SQLitePersonaStore
from .reply_resolver import resolve_message_id
from .sqlite import SQLiteStorage
from .syslog import SQLiteSystemLogStore
from .vectors import SQLiteVectorIndex, VectorMatch

__all__ = [
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
