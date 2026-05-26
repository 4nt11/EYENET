"""GroupCandidate + GroupCandidateMention contracts (API_PLAN §4.12, MODELS §2.20-2.21)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from pydantic import Field

from ._base import DbRowBase
from .enums import CandidateState, GroupKind, MentionKind


class GroupCandidateRow(DbRowBase):
    """Persisted GroupCandidate row (MODELS §2.20)."""

    source_id: UUID
    platform_groupid: str
    kind_hint: GroupKind | None = None
    display_name_hint: str | None = Field(default=None, max_length=512)
    state: CandidateState = CandidateState.DISCOVERED
    score: float = Field(default=0.0, ge=0.0)
    score_breakdown: dict[str, object] = Field(default_factory=dict)
    score_function_version: int = Field(default=1, ge=1)
    first_observed_at_ingest: datetime
    last_observed_at_ingest: datetime
    reviewed_at: datetime | None = None
    reviewed_by: str | None = Field(default=None, max_length=256)
    rejection_reason: str | None = Field(default=None, max_length=2048)
    assigned_collector_id: UUID | None = None
    resulting_group_id: UUID | None = None


class GroupCandidateMentionRow(DbRowBase):
    """Persisted GroupCandidateMention row (MODELS §2.21)."""

    candidate_id: UUID
    observed_by_collector_id: UUID
    observed_in_group_id: UUID
    seed_root_id: UUID | None = None
    depth_from_root: int = Field(ge=0)
    mention_evidence_ref: str = Field(min_length=1, max_length=512)
    mention_kind: MentionKind
    mentioned_at_source: datetime
    mentioned_at_ingest: datetime
    mentioning_actor_id: UUID
    mentioning_actor_role_signal: str | None = Field(default=None, max_length=128)


@dataclass
class EligibilityInputs:
    """Pre-computed inputs for per-collector eligibility evaluation (API_PLAN §4.12.3).

    ``min_depth_by_collector`` is the primary predicate — the eligibility
    check at M9.D3 computes ``eligible(C, Z) := min_depth_by_collector[C.id]
    <= C.config.max_auto_join_depth`` for each candidate collector.
    """

    candidate: GroupCandidateRow
    mentions: list[GroupCandidateMentionRow] = field(default_factory=list)
    # min(depth_from_root) per collector_id across all seed_root_id paths
    min_depth_by_collector: dict[UUID, int] = field(default_factory=dict)


__all__ = [
    "EligibilityInputs",
    "GroupCandidateMentionRow",
    "GroupCandidateRow",
]
