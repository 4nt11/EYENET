# SPDX-License-Identifier: AGPL-3.0-or-later
"""Crew clustering — connected components of the shared-infrastructure graph.

A "crew" (the operator-facing /actor-groups concept) is a set of accounts that
share operational infrastructure: the connected components of the ``shared_infra``
linkage edges (see :mod:`eyenet.linker.infra_linker`). `@WBpay_mm1888` bridging two
account sub-groups is exactly the edge that makes them one crew, distinct from a
crew that shares no infrastructure with them.

Pure: edges in, crews out. No I/O — the API route loads the edges and resolves
actor labels around this core.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from uuid import UUID

# Only surface the strongest shared indicators per crew (evidence, not a dump).
_TOP_INFRA = 8


@dataclass
class Crew:
    """A connected component of the shared-infra graph."""

    members: list[UUID]  # sorted, len >= 2
    top_infra: list[str]  # most-frequently-shared indicators within the crew, desc
    edge_count: int
    max_score: float
    # The actual pairwise links behind edge_count, strongest first: the operator
    # can SEE every link, not just its count. (actor_a, actor_b, score, shared).
    links: list[tuple[UUID, UUID, float, list[str]]] = field(default_factory=list)


@dataclass
class _Agg:
    members: set[UUID] = field(default_factory=set)
    infra: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    edges: int = 0
    max_score: float = 0.0
    links: list[tuple[UUID, UUID, float, list[str]]] = field(default_factory=list)


def build_crews(edges: list[tuple[UUID, UUID, float, list[str]]]) -> list[Crew]:
    """Cluster ``(actor_a, actor_b, score, shared_indicators)`` edges into crews.

    Union-find over the edges; each component of >= 2 members becomes a crew with
    its shared-indicator frequency, edge count and peak edge score. Deterministic:
    members sorted by id, crews sorted by size then score, descending.
    """
    parent: dict[UUID, UUID] = {}

    def find(x: UUID) -> UUID:
        parent.setdefault(x, x)
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:
            parent[x], x = root, parent[x]
        return root

    def union(a: UUID, b: UUID) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for a, b, _score, _shared in edges:
        union(a, b)

    aggs: dict[UUID, _Agg] = defaultdict(_Agg)
    for a, b, score, shared in edges:
        agg = aggs[find(a)]
        agg.members.add(a)
        agg.members.add(b)
        agg.edges += 1
        agg.max_score = max(agg.max_score, score)
        agg.links.append((a, b, score, shared))
        for v in shared:
            agg.infra[v] += 1

    crews: list[Crew] = []
    for agg in aggs.values():
        if len(agg.members) < 2:  # noqa: PLR2004 — a crew needs >=2 members by definition
            continue
        top = sorted(agg.infra, key=lambda v: (-agg.infra[v], v))[:_TOP_INFRA]
        crews.append(
            Crew(
                members=sorted(agg.members),
                top_infra=top,
                edge_count=agg.edges,
                max_score=round(agg.max_score, 4),
                links=sorted(agg.links, key=lambda e: -e[2]),
            )
        )
    crews.sort(key=lambda c: (len(c.members), c.max_score), reverse=True)
    return crews


__all__ = ["Crew", "build_crews"]
