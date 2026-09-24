# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared-infrastructure linker (anti-spam linkage §B).

Links actors by the operational infrastructure they share — contact handles,
``t.me`` links, wallets extracted by :mod:`eyenet.linker.indicators` — instead of
writing style. On templated-spam populations this is high precision where
stylometry is actively misleading: it separated the "WBpay" and "LV" laundering
crews that char-ngram simhash had fused into one false clique.

Two layers:

- :func:`propose_infra_edges` — pure. actor -> indicator-set in, weighted edges
  out. No I/O; the whole ranking (inverted index, IDF weighting, max-DF guard,
  weighted-Jaccard scoring) is here and unit-tested.
- :func:`run_infra_linker` — thin runner: load actor indicators from stored
  message bodies, call the pure core, persist edges as ``method="shared_infra"``
  PROPOSED linkages (reusing the existing linkage store + state machine).

See ``development/linker-antispam-spec.md`` §3.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import combinations
from typing import TYPE_CHECKING
from uuid import UUID

from eyenet.linker.indicators import extract_indicators

if TYPE_CHECKING:
    from collections.abc import Mapping

    from eyenet.storage.repository import BaseRepository

# An indicator carried by more than this many actors is treated as ambient (a
# group's own service/admin handle, a payment processor everyone tags) and is
# excluded from linking — it would link the whole room. The DF cap is the cheap,
# hard form of IDF down-weighting.
DEFAULT_MAX_DF = 15
# Minimum weighted-Jaccard score for an edge to be proposed.
DEFAULT_WEIGHT_FLOOR = 0.15
# An indicator (or the corpus) must involve at least this many actors to link.
_MIN_DF = 2


@dataclass(frozen=True)
class InfraEdge:
    """One proposed shared-infrastructure link between two actors."""

    actor_a: UUID
    actor_b: UUID
    score: float
    shared: tuple[str, ...]


def _idf(df: int, n_actors: int) -> float:
    # +1 smoothing so a df of n_actors still contributes a little, and never /0.
    return math.log((n_actors + 1) / (df + 1)) + 1.0


def propose_infra_edges(
    actor_indicators: Mapping[UUID, set[str]],
    *,
    max_df: int = DEFAULT_MAX_DF,
    weight_floor: float = DEFAULT_WEIGHT_FLOOR,
) -> list[InfraEdge]:
    """Rank actor pairs by shared-infrastructure overlap (pure).

    Score = IDF-weighted Jaccard over the two actors' indicator sets, counting only
    *linkable* indicators (document frequency in ``[2, max_df]``). Sharing a rare
    handle scores high; sharing only an ambient one scores ~0 (it is excluded).
    Deterministic: actors ordered by id in each edge, edges sorted by score desc.
    """
    n = len(actor_indicators)
    if n < _MIN_DF:
        return []
    # Inverted index + document frequency.
    postings: dict[str, list[UUID]] = {}
    for actor, inds in actor_indicators.items():
        for ind in inds:
            postings.setdefault(ind, []).append(actor)
    df = {ind: len(actors) for ind, actors in postings.items()}
    # Linkable indicators: shared by >=2 actors, not ambient.
    linkable = {ind for ind, d in df.items() if _MIN_DF <= d <= max_df}
    idf = {ind: _idf(df[ind], n) for ind in linkable}

    # Candidate pairs: co-occur in at least one linkable indicator's postings.
    candidates: set[tuple[UUID, UUID]] = set()
    for ind in linkable:
        for a, b in combinations(sorted(postings[ind]), 2):
            candidates.add((a, b))

    edges: list[InfraEdge] = []
    for a, b in candidates:
        ia = actor_indicators[a] & linkable
        ib = actor_indicators[b] & linkable
        shared = ia & ib
        if not shared:
            continue
        union = ia | ib
        num = sum(idf[v] for v in shared)
        den = sum(idf[v] for v in union)
        score = round(num / den, 4) if den > 0 else 0.0
        if score >= weight_floor:
            edges.append(InfraEdge(a, b, score, tuple(sorted(shared))))
    edges.sort(key=lambda e: e.score, reverse=True)
    return edges


async def run_infra_linker(
    storage: BaseRepository,
    *,
    max_df: int = DEFAULT_MAX_DF,
    weight_floor: float = DEFAULT_WEIGHT_FLOOR,
) -> int:
    """Extract indicators from stored message bodies, propose shared-infra edges,
    and persist them as PROPOSED ``shared_infra`` linkages. Returns edge count.

    ponytail: loads all actor bodies into memory (one batch pass, small-operator
    scale). A live per-message indicator sensor + an ``actor_indicator`` index is
    the streaming upgrade (spec §3) when corpora outgrow a single pass.
    """
    bodies_by_actor = await storage.message_bodies_by_actor()
    actor_indicators = {
        actor: set().union(*(extract_indicators(b) for b in bodies)) if bodies else set()
        for actor, bodies in bodies_by_actor.items()
    }
    edges = propose_infra_edges(actor_indicators, max_df=max_df, weight_floor=weight_floor)
    for e in edges:
        await storage.insert_proposed_linkage(
            actor_a=e.actor_a,
            actor_b=e.actor_b,
            method="shared_infra",
            score=e.score,
            evidence={"shared": list(e.shared), "shared_count": len(e.shared)},
        )
    return len(edges)


__all__ = ["InfraEdge", "propose_infra_edges", "run_infra_linker"]
