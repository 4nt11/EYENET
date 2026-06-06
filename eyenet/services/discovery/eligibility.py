# SPDX-License-Identifier: AGPL-3.0-or-later
"""Per-collector candidate eligibility — the real predicate (API_PLAN §4.12.3, M9.E3).

Combines three gates, in order, for each (candidate, collector) pair:

1. **Dedup / redundancy** — if the candidate already resolved to a group with
   active collector coverage, the resolving Case's ``redundancy_policy`` decides
   whether a second/third collector may join (``SKIP_DUAL_COVER``).
2. **Depth** — the collector must reach one of the candidate's mention seed roots
   (``reachable_roots_for_collector``); the minimum reachable depth must be under
   the collector's ``max_auto_join_depth`` (``NO_REACHABLE_ROOT`` / ``OVER_DEPTH``).
3. **Scout availability** — an AVAILABLE scout identity must exist for the source
   (``NO_SCOUT_AVAILABLE``).

Otherwise ``OK``. This replaces the M9.D3 stub: ``GET /v1/candidates/{id}`` now
surfaces real verdicts, and the CollectorSupervisor (M9.E3) gates a join on the
assigned collector's verdict before dispatch. ``DEFERRED_TO_RUNTIME`` remains a
declared wire value (the enum stays stable) but is no longer emitted.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from eyenet.contracts.enums import RedundancyPolicy

if TYPE_CHECKING:
    from uuid import UUID

    from eyenet.contracts.candidate import EligibilityInputs
    from eyenet.contracts.case import CaseRow
    from eyenet.contracts.collector import CollectorRow
    from eyenet.storage.repository import BaseRepository

# Default depth ceiling when a collector's opaque config omits the key. Mirrors
# the API_PLAN §4.12.3 example. A mention AT this depth is over the limit
# (the check is ``min_depth >= max``).
_DEFAULT_MAX_AUTO_JOIN_DEPTH = 2
# prefer_dual allows a second collector but skips a third+ (≥ this many active).
_DUAL_COVER_LIMIT = 2


class CollectorEligibilityResult(StrEnum):
    """Eligibility verdict for a (candidate, collector) pair."""

    OK = "ok"
    SKIP_DUAL_COVER = "skip_dual_cover"
    NO_REACHABLE_ROOT = "no_reachable_root"
    OVER_DEPTH = "over_depth"
    NO_SCOUT_AVAILABLE = "no_scout_available"
    # Retained for wire stability (the M9.D3 era). No longer emitted.
    DEFERRED_TO_RUNTIME = "deferred_to_runtime"


@dataclass(frozen=True)
class CollectorEligibility:
    """One collector's eligibility verdict for a candidate."""

    collector_id: UUID
    result: CollectorEligibilityResult
    reason: str


def _max_auto_join_depth(collector: CollectorRow) -> int:
    raw = collector.config.get("max_auto_join_depth", _DEFAULT_MAX_AUTO_JOIN_DEPTH)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return _DEFAULT_MAX_AUTO_JOIN_DEPTH


def _evaluate(
    *,
    inputs: EligibilityInputs,
    collector: CollectorRow,
    case: CaseRow | None,
    active_membership_count: int,
    reachable_roots: set[UUID],
) -> tuple[CollectorEligibilityResult, str]:
    """Pure structural gate evaluation for one collector (scout availability is
    checked by the caller, which holds the source-level answer)."""
    # 1. Dedup / redundancy.
    if active_membership_count > 0:
        policy = case.redundancy_policy if case is not None else RedundancyPolicy.PREFER_SINGLE
        if policy is RedundancyPolicy.PREFER_SINGLE:
            return (
                CollectorEligibilityResult.SKIP_DUAL_COVER,
                "group already covered and case redundancy_policy=prefer_single",
            )
        if policy is RedundancyPolicy.PREFER_DUAL and active_membership_count >= _DUAL_COVER_LIMIT:
            return (
                CollectorEligibilityResult.SKIP_DUAL_COVER,
                "group already has dual coverage (redundancy_policy=prefer_dual)",
            )

    # 2. Depth.
    reachable_depths = [
        m.depth_from_root
        for m in inputs.mentions
        if m.seed_root_id is not None and m.seed_root_id in reachable_roots
    ]
    if not reachable_depths:
        return (
            CollectorEligibilityResult.NO_REACHABLE_ROOT,
            "collector reaches none of the candidate's mention seed roots",
        )
    min_depth = min(reachable_depths)
    max_depth = _max_auto_join_depth(collector)
    if min_depth >= max_depth:
        return (
            CollectorEligibilityResult.OVER_DEPTH,
            f"min reachable depth {min_depth} >= max_auto_join_depth {max_depth}",
        )
    return (CollectorEligibilityResult.OK, "eligible")


async def collector_eligibility(
    candidate_id: UUID,
    collector_id: UUID,
    storage: BaseRepository,
) -> CollectorEligibility:
    """Evaluate a single (candidate, collector) pair (the supervisor's gate).

    Raises :class:`ValueError` if the candidate or collector does not exist.
    """
    inputs = await storage.compute_eligibility_inputs(candidate_id)
    collector = await storage.get_collector(collector_id)
    if collector is None:
        raise ValueError(f"collector {collector_id} not found")
    candidate = inputs.candidate
    case = await storage.resolve_case_for_candidate(candidate_id)
    active = (
        await storage.list_active_memberships(group_id=candidate.resulting_group_id)
        if candidate.resulting_group_id is not None
        else []
    )
    reachable = await storage.reachable_roots_for_collector(collector_id)
    result, reason = _evaluate(
        inputs=inputs,
        collector=collector,
        case=case,
        active_membership_count=len(active),
        reachable_roots=reachable,
    )
    # 3. Scout availability — only relevant once the structural gates pass.
    if result is CollectorEligibilityResult.OK and not await storage.has_available_scout(
        candidate.source_id
    ):
        result, reason = (
            CollectorEligibilityResult.NO_SCOUT_AVAILABLE,
            "no available scout identity for the source",
        )
    return CollectorEligibility(collector_id=collector_id, result=result, reason=reason)


async def eligibility_for_candidate(
    candidate_id: UUID,
    storage: BaseRepository,
) -> list[CollectorEligibility]:
    """Return per-collector eligibility across the whole fleet (API_PLAN §4.12.3).

    Surfaced read-only on ``GET /v1/candidates/{id}`` — the UI's "approve & assign
    to…" picker enables only ``OK`` collectors. Raises :class:`ValueError` if the
    candidate does not exist.
    """
    inputs = await storage.compute_eligibility_inputs(candidate_id)
    candidate = inputs.candidate
    collectors = await storage.list_collectors()
    case = await storage.resolve_case_for_candidate(candidate_id)
    active = (
        await storage.list_active_memberships(group_id=candidate.resulting_group_id)
        if candidate.resulting_group_id is not None
        else []
    )
    has_scout = await storage.has_available_scout(candidate.source_id)

    verdicts: list[CollectorEligibility] = []
    for collector in collectors:
        reachable = await storage.reachable_roots_for_collector(collector.id)
        result, reason = _evaluate(
            inputs=inputs,
            collector=collector,
            case=case,
            active_membership_count=len(active),
            reachable_roots=reachable,
        )
        if result is CollectorEligibilityResult.OK and not has_scout:
            result, reason = (
                CollectorEligibilityResult.NO_SCOUT_AVAILABLE,
                "no available scout identity for the source",
            )
        verdicts.append(
            CollectorEligibility(collector_id=collector.id, result=result, reason=reason)
        )
    return verdicts


__all__ = [
    "CollectorEligibility",
    "CollectorEligibilityResult",
    "collector_eligibility",
    "eligibility_for_candidate",
]
