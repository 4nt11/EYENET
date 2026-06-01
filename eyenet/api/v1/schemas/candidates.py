# SPDX-License-Identifier: AGPL-3.0-or-later
"""GroupCandidate triage schemas (M9.D3, API_PLAN §3.9 / §4.12).

Projections over :class:`GroupCandidateRow` / :class:`GroupCandidateMentionRow`
and the (stubbed) :class:`CollectorEligibility`. The candidate state machine is
enforced by ``transition_candidate`` in storage; these schemas are read/write
projections only.

OpenAPI: `contracts/openapi/eyenet.v1.yaml` — Candidate*, CandidateMention,
CandidateEligibility, CursorPageCandidateSummary (pinned in slice 4).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from eyenet.contracts.candidate import GroupCandidateMentionRow, GroupCandidateRow
from eyenet.contracts.enums import CandidateState, GroupKind, MentionKind
from eyenet.services.discovery.eligibility import CollectorEligibility, CollectorEligibilityResult

from ._base import ApiSchema
from .pagination import CursorPage


class CandidateSummary(ApiSchema):
    """Projection of MODELS §2.20 GroupCandidate for the triage queue."""

    candidate_id: UUID
    source_id: UUID
    platform_groupid: str = Field(max_length=512)
    kind_hint: GroupKind | None = None
    display_name_hint: str | None = None
    state: CandidateState
    score: float = Field(ge=0.0)
    first_observed_at_ingest: datetime
    last_observed_at_ingest: datetime

    @classmethod
    def from_domain(cls, row: GroupCandidateRow) -> CandidateSummary:
        return cls(
            candidate_id=row.id,
            source_id=row.source_id,
            platform_groupid=row.platform_groupid,
            kind_hint=row.kind_hint,
            display_name_hint=row.display_name_hint,
            state=row.state,
            score=row.score,
            first_observed_at_ingest=row.first_observed_at_ingest,
            last_observed_at_ingest=row.last_observed_at_ingest,
        )


class CandidateMentionView(ApiSchema):
    """Projection of MODELS §2.21 GroupCandidateMention (provenance)."""

    mention_id: UUID
    observed_by_collector_id: UUID
    observed_in_group_id: UUID
    seed_root_id: UUID | None = None
    depth_from_root: int = Field(ge=0)
    mention_kind: MentionKind
    mention_evidence_ref: str
    mentioned_at_ingest: datetime
    mentioning_actor_id: UUID
    mentioning_actor_role_signal: str | None = None

    @classmethod
    def from_domain(cls, row: GroupCandidateMentionRow) -> CandidateMentionView:
        return cls(
            mention_id=row.id,
            observed_by_collector_id=row.observed_by_collector_id,
            observed_in_group_id=row.observed_in_group_id,
            seed_root_id=row.seed_root_id,
            depth_from_root=row.depth_from_root,
            mention_kind=row.mention_kind,
            mention_evidence_ref=row.mention_evidence_ref,
            mentioned_at_ingest=row.mentioned_at_ingest,
            mentioning_actor_id=row.mentioning_actor_id,
            mentioning_actor_role_signal=row.mentioning_actor_role_signal,
        )


class CandidateEligibilityView(ApiSchema):
    """Per-collector eligibility entry (STUB in M9.D3 — see eligibility.py)."""

    collector_id: UUID
    result: CollectorEligibilityResult
    reason: str

    @classmethod
    def from_domain(cls, item: CollectorEligibility) -> CandidateEligibilityView:
        return cls(collector_id=item.collector_id, result=item.result, reason=item.reason)


class CandidateDetail(CandidateSummary):
    """Projection for `GET /v1/candidates/{id}` — mentions, score breakdown,
    review state, and the (stubbed) per-collector eligibility block."""

    score_breakdown: dict[str, object] = Field(default_factory=dict)
    reviewed_at: datetime | None = None
    reviewed_by: str | None = None
    rejection_reason: str | None = None
    assigned_collector_id: UUID | None = None
    resulting_group_id: UUID | None = None
    mentions: list[CandidateMentionView] = Field(default_factory=list)
    eligibility_per_collector: list[CandidateEligibilityView] = Field(default_factory=list)


class ApproveCandidateRequest(ApiSchema):
    """Body of `POST /v1/candidates/{id}/approve`."""

    assigned_collector_id: UUID


class RejectCandidateRequest(ApiSchema):
    """Body of `POST /v1/candidates/{id}/reject`."""

    reason: str = Field(min_length=1, max_length=2048)


class ParkCandidateRequest(ApiSchema):
    """Body of `POST /v1/candidates/{id}/park`."""

    reason: str = Field(min_length=1, max_length=2048)


class CursorPageCandidateSummary(CursorPage[CandidateSummary]):
    """200 page response for `GET /v1/candidates`."""


__all__ = [
    "ApproveCandidateRequest",
    "CandidateDetail",
    "CandidateEligibilityView",
    "CandidateMentionView",
    "CandidateSummary",
    "CursorPageCandidateSummary",
    "ParkCandidateRequest",
    "RejectCandidateRequest",
]
