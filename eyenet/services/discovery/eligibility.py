# SPDX-License-Identifier: AGPL-3.0-or-later
"""Per-collector candidate eligibility (API_PLAN §4.12.3).

**M9.D3 ships a STUB.** The full predicate — dedup against active
memberships, depth-from-root vs the collector's ``max_auto_join_depth``, and
identity-pool / scout availability — depends on the Group E runtime
(CollectorSupervisor + identity pool) that does not exist yet. Until then:

* :func:`eligibility_for_candidate` returns one ``DEFERRED_TO_RUNTIME`` entry
  per collector that has a mention path to the candidate (the collectors the
  real predicate would evaluate), surfaced read-only on ``GET /v1/candidates/{id}``.
* ``POST /v1/candidates/{id}/approve`` does **NOT** gate on this result — it
  validates existence + a legal state transition only. The eligibility gate is
  operator-trusted in v1 (a deliberate, documented weaker-safety posture).

The seam: the real implementation reads ``compute_eligibility_inputs`` (already
returns ``min_depth_by_collector``), joins ``list_active_memberships`` for the
dedup/dual-cover decision, and consults the identity pool for scout
availability. See ``development/API_PLAN.md`` §4.12.3.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID

    from eyenet.storage.repository import BaseRepository


class CollectorEligibilityResult(StrEnum):
    """Eligibility verdict for a (candidate, collector) pair.

    Only ``DEFERRED_TO_RUNTIME`` is emitted in M9.D3. The remaining variants
    are the Group E vocabulary, declared here so the wire enum is stable when
    the real predicate lands.
    """

    DEFERRED_TO_RUNTIME = "deferred_to_runtime"
    # TODO(Group E): the real verdicts.
    OK = "ok"
    SKIP_DUAL_COVER = "skip_dual_cover"
    NO_REACHABLE_ROOT = "no_reachable_root"
    OVER_DEPTH = "over_depth"
    NO_SCOUT_AVAILABLE = "no_scout_available"


@dataclass(frozen=True)
class CollectorEligibility:
    """One collector's eligibility verdict for a candidate."""

    collector_id: UUID
    result: CollectorEligibilityResult
    reason: str


_DEFERRED_REASON = (
    "dedup / depth / identity-pool scout availability resolved by the Group E "
    "supervisor; this gate is not yet enforced (M9.D3 stub)"
)


async def eligibility_for_candidate(
    candidate_id: UUID,
    storage: BaseRepository,
) -> list[CollectorEligibility]:
    """Return the (stubbed) per-collector eligibility for a candidate.

    One entry per collector that has a mention path to this candidate (the set
    the real predicate would score), each ``DEFERRED_TO_RUNTIME``. Raises
    :class:`ValueError` if the candidate does not exist (caller checks first).
    """
    inputs = await storage.compute_eligibility_inputs(candidate_id)
    return [
        CollectorEligibility(
            collector_id=collector_id,
            result=CollectorEligibilityResult.DEFERRED_TO_RUNTIME,
            reason=_DEFERRED_REASON,
        )
        for collector_id in inputs.min_depth_by_collector
    ]


__all__ = [
    "CollectorEligibility",
    "CollectorEligibilityResult",
    "eligibility_for_candidate",
]
