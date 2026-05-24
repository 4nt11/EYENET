"""SQLiteVectorIndex — flat-SQL Hamming search for 64-bit simhashes.

PLAN §5.2: VectorIndex keys are (actor_id, primitive_name). Values are 64-bit
simhashes stored as signed integers (SQLite INTEGER). Hamming distance via
bit_count(v ^ query). Capped at ~1M rows before sqlite-vec kNN is warranted.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

import structlog
from opentelemetry import trace
from sqlalchemy import event, text
from sqlalchemy.engine import Engine

from eyenet.contracts.storage import VectorIndex

_log = structlog.get_logger(__name__)
_tracer = trace.get_tracer("eyenet.storage.vectors")


def _hex_to_int(h: str) -> int:
    """Convert a 16-char hex string to a signed 64-bit integer for SQLite storage."""
    unsigned = int(h, 16)
    if unsigned >= (1 << 63):
        return unsigned - (1 << 64)
    return unsigned


def _int_to_hex(n: int) -> str:
    """Convert a signed 64-bit integer back to a 16-char hex string."""
    if n < 0:
        n += 1 << 64
    return format(n, "016x")


def _register_hamming64(engine: Engine) -> None:
    """Register `hamming64(a, b) -> int` on every new connection.

    Computes `popcount(a XOR b)` as a Python UDF, bypassing SQLite's lack of a
    native XOR operator and `bit_count` on older SQLite versions.
    The UDF is deterministic and pure Python — no native extensions needed.
    """

    def _hamming64(a: int | None, b: int | None) -> int:
        if a is None or b is None:
            return 0
        xor = (a ^ b) & 0xFFFF_FFFF_FFFF_FFFF
        return bin(xor).count("1")

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn: Any, _record: Any) -> None:
        dbapi_conn.create_function("hamming64", 2, _hamming64, deterministic=True)

    # Also register on any already-open connection in the pool (important for
    # StaticPool used in unit tests, where "connect" fires only once).
    try:
        with engine.connect() as conn:
            conn.connection.create_function("hamming64", 2, _hamming64, deterministic=True)
    except Exception as exc:
        # StaticPool may already have the function bound; non-fatal but log it
        # so silent breakage in a unit-test pool config is visible.
        _log.debug("vector_index.hamming64_register_skipped", error=str(exc))


@dataclass(frozen=True)
class VectorMatch:
    actor_id: UUID
    distance: int
    simhash_hex: str  # the neighbor's stored simhash value


class SQLiteVectorIndex(VectorIndex):
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        _register_hamming64(engine)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS vector_signature (
                        actor_id TEXT NOT NULL,
                        primitive_name TEXT NOT NULL,
                        simhash INTEGER NOT NULL,
                        PRIMARY KEY (actor_id, primitive_name)
                    )
                    """
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_vs_primitive ON vector_signature(primitive_name)"
                )
            )

    async def upsert_simhash(
        self,
        actor_id: UUID,
        primitive_name: str,
        simhash_hex: str,
    ) -> None:
        with (
            _tracer.start_as_current_span(
                "storage.vectors.upsert_simhash",
                attributes={
                    "actor.id": str(actor_id),
                    "primitive.name": primitive_name,
                },
            ),
            self._engine.begin() as conn,
        ):
            conn.execute(
                text(
                    """
                    INSERT INTO vector_signature (actor_id, primitive_name, simhash)
                    VALUES (:aid, :pname, :sh)
                    ON CONFLICT(actor_id, primitive_name)
                    DO UPDATE SET simhash = excluded.simhash
                    """
                ),
                {"aid": str(actor_id), "pname": primitive_name, "sh": _hex_to_int(simhash_hex)},
            )

    async def nearest(
        self,
        primitive_name: str,
        simhash_hex: str,
        max_distance: int,
        limit: int = 50,
        exclude_actor_id: UUID | None = None,
    ) -> list[VectorMatch]:
        """Return actors within `max_distance` Hamming bits, sorted ascending.

        Each VectorMatch carries the neighbor's stored simhash_hex so the
        Linker can pass both values to comparator.compare() for evidence.
        """
        query_int = _hex_to_int(simhash_hex)
        with (
            _tracer.start_as_current_span(
                "storage.vectors.nearest",
                attributes={
                    "primitive.name": primitive_name,
                    "query.max_distance": max_distance,
                    "query.limit": limit,
                },
            ) as nearest_span,
            self._engine.begin() as conn,
        ):
            if exclude_actor_id is not None:
                rows = conn.execute(
                    text(
                        """
                        SELECT actor_id, simhash, dist FROM (
                            SELECT actor_id, simhash,
                                   hamming64(:q, simhash) AS dist
                            FROM vector_signature
                            WHERE primitive_name = :p AND actor_id != :excl
                        ) WHERE dist <= :max_d
                        ORDER BY dist ASC
                        LIMIT :lim
                        """
                    ),
                    {
                        "q": query_int,
                        "p": primitive_name,
                        "excl": str(exclude_actor_id),
                        "max_d": max_distance,
                        "lim": limit,
                    },
                ).fetchall()
            else:
                rows = conn.execute(
                    text(
                        """
                        SELECT actor_id, simhash, dist FROM (
                            SELECT actor_id, simhash,
                                   hamming64(:q, simhash) AS dist
                            FROM vector_signature
                            WHERE primitive_name = :p
                        ) WHERE dist <= :max_d
                        ORDER BY dist ASC
                        LIMIT :lim
                        """
                    ),
                    {
                        "q": query_int,
                        "p": primitive_name,
                        "max_d": max_distance,
                        "lim": limit,
                    },
                ).fetchall()
            matches = [
                VectorMatch(
                    actor_id=UUID(str(r[0])),
                    distance=int(r[2]),
                    simhash_hex=_int_to_hex(int(r[1])),
                )
                for r in rows
            ]
            nearest_span.set_attribute("result.count", len(matches))
            return matches


__all__ = ["SQLiteVectorIndex", "VectorMatch"]
