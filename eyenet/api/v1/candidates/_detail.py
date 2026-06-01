# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared CandidateDetail projection for the Candidate handlers (M9.D3)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from eyenet.api.v1.schemas.candidates import (
    CandidateDetail,
    CandidateEligibilityView,
    CandidateMentionView,
)
from eyenet.services.discovery.eligibility import eligibility_for_candidate

if TYPE_CHECKING:
    from eyenet.storage.repository import BaseRepository


async def build_candidate_detail(
    storage: BaseRepository, candidate_id: UUID
) -> CandidateDetail | None:
    """Assemble the full :class:`CandidateDetail`, or ``None`` if absent.

    Mentions + ``min_depth_by_collector`` come from
    ``compute_eligibility_inputs``; the eligibility block is the M9.D3 stub.
    """
    candidate = await storage.get_candidate(candidate_id)
    if candidate is None:
        return None
    inputs = await storage.compute_eligibility_inputs(candidate_id)
    eligibility = await eligibility_for_candidate(candidate_id, storage)
    return CandidateDetail(
        candidate_id=candidate.id,
        source_id=candidate.source_id,
        platform_groupid=candidate.platform_groupid,
        kind_hint=candidate.kind_hint,
        display_name_hint=candidate.display_name_hint,
        state=candidate.state,
        score=candidate.score,
        first_observed_at_ingest=candidate.first_observed_at_ingest,
        last_observed_at_ingest=candidate.last_observed_at_ingest,
        score_breakdown=candidate.score_breakdown,
        reviewed_at=candidate.reviewed_at,
        reviewed_by=candidate.reviewed_by,
        rejection_reason=candidate.rejection_reason,
        assigned_collector_id=candidate.assigned_collector_id,
        resulting_group_id=candidate.resulting_group_id,
        mentions=[CandidateMentionView.from_domain(m) for m in inputs.mentions],
        eligibility_per_collector=[CandidateEligibilityView.from_domain(e) for e in eligibility],
    )
