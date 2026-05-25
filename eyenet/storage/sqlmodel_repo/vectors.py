# SPDX-License-Identifier: AGPL-3.0-or-later
"""VectorsMixin — flat-SQL Hamming search over `vector_signature`.

The `hamming64(a, b) -> int` UDF and the `vector_signature` table DDL are
registered/created by the dialect layer (`sqlite/database.py`). This
mixin only emits SQL.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from opentelemetry import trace
from sqlalchemy import text

from ._helpers import safe_session

_tracer = trace.get_tracer("eyenet.storage.sqlmodel_repo.vectors")


def _hex_to_int(h: str) -> int:
    unsigned = int(h, 16)
    if unsigned >= (1 << 63):
        return unsigned - (1 << 64)
    return unsigned


def _int_to_hex(n: int) -> str:
    if n < 0:
        n += 1 << 64
    return format(n, "016x")


@dataclass(frozen=True)
class VectorMatch:
    actor_id: UUID
    distance: int
    simhash_hex: str


class VectorsMixin:
    async def upsert_simhash(
        self,
        actor_id: UUID,
        primitive_name: str,
        simhash_hex: str,
    ) -> None:
        with _tracer.start_as_current_span(
            "storage.vectors.upsert_simhash",
            attributes={
                "actor.id": str(actor_id),
                "primitive.name": primitive_name,
            },
        ):
            async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
                await session.exec(  # type: ignore[call-overload]
                    text(
                        """
                        INSERT INTO vector_signature (actor_id, primitive_name, simhash)
                        VALUES (:aid, :pname, :sh)
                        ON CONFLICT(actor_id, primitive_name)
                        DO UPDATE SET simhash = excluded.simhash
                        """
                    ),
                    params={
                        "aid": str(actor_id),
                        "pname": primitive_name,
                        "sh": _hex_to_int(simhash_hex),
                    },
                )
                await session.commit()

    async def nearest_simhashes(
        self,
        primitive_name: str,
        simhash_hex: str,
        max_distance: int,
        limit: int = 50,
        exclude_actor_id: UUID | None = None,
    ) -> list[VectorMatch]:
        query_int = _hex_to_int(simhash_hex)
        with _tracer.start_as_current_span(
            "storage.vectors.nearest",
            attributes={
                "primitive.name": primitive_name,
                "query.max_distance": max_distance,
                "query.limit": limit,
            },
        ) as nearest_span:
            async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
                if exclude_actor_id is not None:
                    result = await session.exec(  # type: ignore[call-overload]
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
                        params={
                            "q": query_int,
                            "p": primitive_name,
                            "excl": str(exclude_actor_id),
                            "max_d": max_distance,
                            "lim": limit,
                        },
                    )
                else:
                    result = await session.exec(  # type: ignore[call-overload]
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
                        params={
                            "q": query_int,
                            "p": primitive_name,
                            "max_d": max_distance,
                            "lim": limit,
                        },
                    )
                rows = result.fetchall()
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


__all__ = ["VectorMatch", "VectorsMixin"]
