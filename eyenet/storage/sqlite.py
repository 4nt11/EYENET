"""`SQLiteStorage` aggregate — wires all sub-stores to per-store engines."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.engine import Engine

from eyenet.contracts.storage import (
    CorpusStore,
    GraphStore,
    LinkageStore,
    MessageStore,
    ObservationStore,
    PersonaStore,
    ProfileStore,
    Storage,
    VectorIndex,
)

from .audit import SQLiteAuditStore
from .corpus import SQLiteCorpusStore
from .cursors import SQLiteCursorStore
from .engines import StoreName, close_all, open_all
from .graph import SQLiteGraphStore
from .linkages import SQLiteLinkageStore
from .messages import SQLiteMessageStore
from .observations import SQLiteObservationStore
from .personas import SQLitePersonaStore
from .profiles import SQLiteProfileStore
from .syslog import SQLiteSystemLogStore
from .vectors import SQLiteVectorIndex


class SQLiteStorage(Storage):
    """Aggregate `Storage` impl. Holds per-store engines; sub-stores are
    instantiated lazily on attribute access and reused thereafter.
    """

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._engines: dict[StoreName, Engine] = open_all(data_dir)
        self._messages = SQLiteMessageStore(self._engines[StoreName.MESSAGES])
        self._corpus = SQLiteCorpusStore(self._engines[StoreName.MESSAGES])
        self._cursors = SQLiteCursorStore(self._engines[StoreName.CORPUS])
        self._observations = SQLiteObservationStore(self._engines[StoreName.OBSERVATIONS])
        self._profiles = SQLiteProfileStore(self._engines[StoreName.PROFILES])
        self._vectors = SQLiteVectorIndex(self._engines[StoreName.VECTORS])
        self._graph = SQLiteGraphStore(self._engines[StoreName.GRAPH])
        self._linkages = SQLiteLinkageStore(self._engines[StoreName.PROFILES])
        self._personas = SQLitePersonaStore(self._engines[StoreName.PROFILES])
        self._audit = SQLiteAuditStore(
            self._engines[StoreName.AUDIT],
            ndjson_path=data_dir / "audit.ndjson",
        )
        self._syslog = SQLiteSystemLogStore(self._engines[StoreName.SYSLOG])

    @property
    def messages(self) -> MessageStore:
        return self._messages

    @property
    def corpus(self) -> CorpusStore:
        return self._corpus

    @property
    def cursors(self) -> SQLiteCursorStore:
        return self._cursors

    @property
    def observations(self) -> ObservationStore:
        return self._observations

    @property
    def profiles(self) -> ProfileStore:
        return self._profiles

    @property
    def vector_index(self) -> VectorIndex:
        return self._vectors

    @property
    def graph(self) -> GraphStore:
        return self._graph

    @property
    def linkages(self) -> LinkageStore:
        return self._linkages

    @property
    def personas(self) -> PersonaStore:
        return self._personas

    @property
    def audit(self) -> SQLiteAuditStore:
        return self._audit

    @property
    def syslog(self) -> SQLiteSystemLogStore:
        return self._syslog

    @property
    def data_dir(self) -> Path:
        return self._data_dir

    async def close(self) -> None:
        close_all(self._engines.values())


__all__ = ["SQLiteStorage"]
