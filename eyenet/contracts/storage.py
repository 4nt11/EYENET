"""`Storage` ABCs — abstract factory for the persistence layer (PLAN §5.2).

v0 implementation: SQLite (one DB file per store). Cross-store joins are
forbidden — the boundaries are documented in PLAN §5.2 and crossings live in
application code, NOT in the storage layer.

Stores:
  MessageStore     — raw messages by `evidence_ref`
  CorpusStore      — append-only per-actor message history
  ObservationStore — observations indexed by (actor_id, primitive, ts)
  ProfileStore     — current + historical profile states
  VectorIndex      — similarity search (sqlite-vec / Hamming flat-SQL)
  GraphStore       — nodes + edges, typed relations
  LinkageStore     — linkage lifecycle; proposed/suspected/confirmed/rejected rows
  PersonaStore     — union-find persona cluster; forward + reverse views
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any
from uuid import UUID


class MessageStore(ABC):
    @abstractmethod
    async def get_by_evidence_ref(self, evidence_ref: str) -> bytes | None:
        """Return the raw message body bytes; None if unknown."""

    @abstractmethod
    async def put(self, evidence_ref: str, body: bytes) -> None: ...


class CorpusStore(ABC):
    @abstractmethod
    async def append(
        self,
        actor_id: UUID,
        ts: datetime,
        evidence_ref: str,
        message_length: int,
        language: str | None,
    ) -> None: ...

    @abstractmethod
    async def iter_since(
        self,
        actor_id: UUID,
        since_ts: datetime,
        since_msg_id: UUID,
    ) -> list[tuple[datetime, UUID, str]]:
        """Return `[(ts, msg_id, evidence_ref), ...]` strictly after the cursor.

        Per-primitive cursoring lives in the sensor (CorpusCursor); the
        store only knows how to walk forward from a given (ts, msg_id) pair.
        Pagination semantics (chunk size, streaming) land in M2 if needed.
        """

    async def iter_since_with_reply(
        self,
        actor_id: UUID,
        since_ts: datetime,
        since_msg_id: UUID,
    ) -> list[tuple[datetime, UUID, str, UUID | None]]:
        """Like `iter_since` but also returns `reply_to_msg_id` per row.

        Default implementation delegates to `iter_since` and fills the reply
        field with `None` — override in concrete impls that have the column.
        Returns `[(ts, msg_id, evidence_ref, reply_to_msg_id | None), ...]`.
        """
        rows = await self.iter_since(actor_id, since_ts, since_msg_id)
        return [(ts, mid, ref, None) for ts, mid, ref in rows]


class ObservationStore(ABC):
    @abstractmethod
    async def put(self, observation_row: object) -> None:
        """Persist an `ObservationRow`. Type-erased to keep this layer
        independent of contracts.observation."""

    @abstractmethod
    async def latest(
        self,
        actor_id: UUID,
        primitive_name: str,
        limit: int = 1,
    ) -> list[object]: ...

    @abstractmethod
    async def by_evidence_and_primitive(
        self,
        evidence_ref: str,
        primitive_name: str,
    ) -> object | None:
        """Return the most-recent ObservationRow for (evidence_ref, primitive_name).

        Used by the engine to resolve actor_id from a bus Observation envelope
        (which carries evidence_ref + primitive but not actor_id). Returns None
        if the row has not been persisted yet (sensor/engine race).
        """


class ProfileStore(ABC):
    @abstractmethod
    async def get_current(self, actor_id: UUID) -> object | None:
        """Return current ProfileRow or None."""

    @abstractmethod
    async def upsert_current(self, profile_row: object) -> None: ...

    @abstractmethod
    async def history(self, actor_id: UUID) -> list[object]: ...


class VectorIndex(ABC):
    @abstractmethod
    async def upsert_simhash(
        self,
        actor_id: UUID,
        primitive_name: str,
        simhash_hex: str,
    ) -> None:
        """Store or replace a 64-bit simhash (16-char hex string)."""

    @abstractmethod
    async def nearest(
        self,
        primitive_name: str,
        simhash_hex: str,
        max_distance: int,
        limit: int = 50,
        exclude_actor_id: UUID | None = None,
    ) -> list[Any]:
        """Return list[VectorMatch] sorted by Hamming distance ascending.

        VectorMatch carries (actor_id, distance, simhash_hex).
        Only rows with distance <= max_distance are returned.
        exclude_actor_id suppresses self-matches.
        """


class GraphStore(ABC):
    @abstractmethod
    async def upsert_node(
        self, node_type: str, node_id: UUID, attrs: dict[str, object]
    ) -> None: ...

    @abstractmethod
    async def upsert_edge(
        self,
        edge_type: str,
        src_id: UUID,
        dst_id: UUID,
        attrs: dict[str, object],
    ) -> None: ...

    @abstractmethod
    async def delete_edge(self, edge_type: str, src_id: UUID, dst_id: UUID) -> None:
        """Remove an edge if it exists. No-op if absent."""

    @abstractmethod
    async def neighbors(
        self,
        node_id: UUID,
        edge_type: str | None = None,
    ) -> list[tuple[UUID, str, dict[str, object]]]:
        """Return `[(neighbor_id, edge_type, attrs)]`."""

    @abstractmethod
    async def edges_by_type(
        self,
        edge_type: str,
        src_id: UUID | None = None,
        dst_id: UUID | None = None,
    ) -> list[tuple[UUID, UUID, dict[str, object]]]:
        """Return `[(src_id, dst_id, attrs)]` for edges of a given type."""

    @abstractmethod
    async def stats(self) -> dict[str, int]:
        """Return counts: actors, personas, edges by type."""


class LinkageStore(ABC):
    @abstractmethod
    async def insert_proposed(
        self,
        actor_a: UUID,
        actor_b: UUID,
        method: str,
        score: float,
        evidence: dict[str, Any],
    ) -> object:
        """Insert or update a proposed linkage row. Returns LinkageRow.

        Sorts the pair (actor_a < actor_b) before write. Idempotent on
        (actor_a, actor_b, method, PROPOSED state) — updates score if higher.
        """

    @abstractmethod
    async def transition(
        self,
        linkage_id: UUID,
        new_state: object,
        decided_by: str,
        notes: str | None = None,
    ) -> object:
        """Transition a linkage to a new state. Returns updated LinkageRow.

        Legal transitions:
          PROPOSED  → {SUSPECTED, CONFIRMED, REJECTED, SUPERSEDED}
          SUSPECTED → {CONFIRMED, REJECTED}
          All others are terminal (raise ValueError).
        """

    @abstractmethod
    async def get(self, linkage_id: UUID) -> object | None:
        """Return LinkageRow or None."""

    @abstractmethod
    async def list_linkages(
        self,
        actor_id: UUID | None = None,
        state: object | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[object]:
        """Return list[LinkageRow] filtered by actor_id and/or state."""


class PersonaStore(ABC):
    @abstractmethod
    async def persona_for_actor(self, actor_id: UUID) -> object | None:
        """Return PersonaRow for the actor, or None if unassigned."""

    @abstractmethod
    async def merge_actors(
        self,
        actor_a: UUID,
        actor_b: UUID,
        via_linkage_id: UUID,
    ) -> object:
        """Union-find merge. Returns the surviving PersonaRow.

        Four cases (all in one transaction):
          1. Neither in a persona: create new Persona, add both.
          2. One in a persona: add the other to that persona.
          3. Both in the same persona: no-op, return existing.
          4. Both in different personas: keep older persona_id, fold member_actor_ids,
             rewrite PersonaMembership for absorbed members, delete absorbed row.
        """

    @abstractmethod
    async def split_actor(self, actor_id: UUID) -> object | None:
        """Remove actor from its persona; recompute the cluster from confirmed linkages.

        Used when a linkage is SUPERSEDED and the cluster may now be disconnected.
        Returns the actor's new PersonaRow, or None if the actor has no remaining
        confirmed linkages and is now unassigned.
        """

    @abstractmethod
    async def get_persona(self, persona_id: UUID) -> object | None:
        """Return PersonaRow or None."""

    @abstractmethod
    async def members(self, persona_id: UUID) -> list[UUID]:
        """Return list of actor_ids that are members of this persona."""


class Storage(ABC):
    """Aggregate accessor — concrete impls expose all sub-stores."""

    @property
    @abstractmethod
    def messages(self) -> MessageStore: ...

    @property
    @abstractmethod
    def corpus(self) -> CorpusStore: ...

    @property
    @abstractmethod
    def observations(self) -> ObservationStore: ...

    @property
    @abstractmethod
    def profiles(self) -> ProfileStore: ...

    @property
    @abstractmethod
    def vector_index(self) -> VectorIndex: ...

    @property
    @abstractmethod
    def graph(self) -> GraphStore: ...

    @property
    @abstractmethod
    def linkages(self) -> LinkageStore: ...

    @property
    @abstractmethod
    def personas(self) -> PersonaStore: ...

    @abstractmethod
    async def close(self) -> None: ...


__all__ = [
    "CorpusStore",
    "GraphStore",
    "LinkageStore",
    "MessageStore",
    "ObservationStore",
    "PersonaStore",
    "ProfileStore",
    "Storage",
    "VectorIndex",
]
