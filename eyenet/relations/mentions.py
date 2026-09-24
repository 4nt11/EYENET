# SPDX-License-Identifier: AGPL-3.0-or-later
"""Actor-to-actor relationship builder (mentions + forwards).

Two layers, mirroring :mod:`eyenet.linker.infra_linker`:

- :func:`extract_handles` / :func:`build_relations` — pure. Message rows in,
  aggregated directed edges out. All the resolution and counting is here and
  unit-tested; no I/O.
- :func:`run_relation_builder` — thin runner: load the handle/userid indices and
  the message rows from storage, call the pure core, and replace the materialized
  ``actor_relation`` edge set (a full rebuild, idempotent).

MENTION edges: the message author wrote an ``@handle`` that resolves to another
actor. FORWARD edges: a relayed message (origin author = message author, per the
"origin is the actor" attribution) links the relayer -> the origin author; the
relayer is recorded on the message as ``relayed_by_platform_userid``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from eyenet.contracts.enums import RelationKind

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from datetime import datetime
    from uuid import UUID

    from eyenet.storage.repository import BaseRepository

# Telegram usernames are [A-Za-z0-9_], start with a letter. We accept 3+ chars to
# stay lenient against short/legacy handles; resolution against the actor index is
# the real filter, so an unknown token just drops. The lookbehind rejects an ``@``
# preceded by a word char so an email local part (``name@gmail``) is not read as a
# mention of "gmail".
# ponytail: a regex over bodies, not a full Telegram-entity parse. If we start
# ingesting message entities, resolve from those offsets instead of re-scanning.
_HANDLE_RE = re.compile(r"(?<![A-Za-z0-9_])@([A-Za-z][A-Za-z0-9_]{2,31})")


def extract_handles(body: str | None) -> set[str]:
    """Return the distinct lowercased ``@handle`` tokens in a message body."""
    if not body:
        return set()
    return {m.lower() for m in _HANDLE_RE.findall(body)}


def normalize_handle(handle: str | None) -> str | None:
    """Canonical form of a handle for indexing: strip a leading ``@``, lowercase.

    Telegram usernames are case-insensitive, so the index is keyed lowercase.
    """
    if not handle:
        return None
    return handle.lstrip("@").lower() or None


@dataclass(frozen=True)
class RelationInputRow:
    """One message, reduced to the fields the relation builder needs."""

    from_actor: UUID
    body: str | None
    sent_at: datetime
    source_id: UUID
    forward_origin_actor: UUID | None
    relayed_by_platform_userid: str | None


@dataclass(frozen=True)
class RelationEdge:
    """One materialized directed actor-to-actor edge."""

    source_id: UUID
    from_actor: UUID
    to_actor: UUID
    kind: RelationKind
    count: int
    first_seen: datetime
    last_seen: datetime


def build_relations(
    rows: Iterable[RelationInputRow],
    handle_to_actor: Mapping[str, UUID],
    actor_by_userid: Mapping[str, UUID],
) -> list[RelationEdge]:
    """Aggregate message rows into directed actor-to-actor edges (pure).

    Self-edges (an actor mentioning/relaying themselves) are dropped. Edges are
    deduped per (from, to, kind) with an occurrence count and the min/max source
    timestamp, and returned sorted by count desc then (from, to) for determinism.
    """
    acc: dict[tuple[UUID, UUID, RelationKind], list[Any]] = {}

    def _bump(src: UUID, frm: UUID, to: UUID, kind: RelationKind, ts: datetime) -> None:
        if frm == to:
            return
        key = (frm, to, kind)
        cur = acc.get(key)
        if cur is None:
            acc[key] = [src, 1, ts, ts]
        else:
            cur[1] += 1
            cur[2] = min(cur[2], ts)
            cur[3] = max(cur[3], ts)

    for row in rows:
        for handle in extract_handles(row.body):
            to = handle_to_actor.get(handle)
            if to is not None:
                _bump(row.source_id, row.from_actor, to, RelationKind.MENTION, row.sent_at)
        if row.forward_origin_actor is not None and row.relayed_by_platform_userid:
            relayer = actor_by_userid.get(row.relayed_by_platform_userid)
            if relayer is not None:
                _bump(
                    row.source_id,
                    relayer,
                    row.forward_origin_actor,
                    RelationKind.FORWARD,
                    row.sent_at,
                )

    edges = [
        RelationEdge(src, frm, to, kind, count, first, last)
        for (frm, to, kind), (src, count, first, last) in acc.items()
    ]
    edges.sort(key=lambda e: (-e.count, str(e.from_actor), str(e.to_actor)))
    return edges


async def run_relation_builder(storage: BaseRepository) -> int:
    """Rebuild the ``actor_relation`` edge set from stored messages. Returns edges.

    ponytail: one in-memory pass over every message (small-operator scale, same as
    the infra linker). A per-message relation sensor is the streaming upgrade if a
    corpus outgrows a single pass.
    """
    handle_to_actor = await storage.handle_to_actor_index()
    actor_by_userid = await storage.actor_id_by_platform_userid()
    raw = await storage.relation_input_rows()
    rows = [
        RelationInputRow(
            from_actor=r[0],
            body=r[1],
            sent_at=r[2],
            source_id=r[3],
            forward_origin_actor=r[4],
            relayed_by_platform_userid=r[5],
        )
        for r in raw
    ]
    edges = build_relations(rows, handle_to_actor, actor_by_userid)
    await storage.replace_actor_relations(
        [
            (
                e.source_id,
                e.from_actor,
                e.to_actor,
                e.kind,
                e.count,
                e.first_seen,
                e.last_seen,
            )
            for e in edges
        ]
    )
    return len(edges)


__all__ = [
    "RelationEdge",
    "RelationInputRow",
    "build_relations",
    "extract_handles",
    "normalize_handle",
    "run_relation_builder",
]
