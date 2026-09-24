# SPDX-License-Identifier: AGPL-3.0-or-later
"""Monitored-groups schemas — a source-agnostic view over GroupCandidate.

Every group an operator has vision over (joined, discovered via descent, or seen
directly in an identity's dialogs/rooms) is a `GroupCandidate` row; this projects
it into a group-centric `GroupSummary` with a derived `status`. Join-at-will
(`JoinGroupRequest`) reuses the candidate approve machinery.

OpenAPI: `contracts/openapi/eyenet.v1.yaml` — GroupSummary, CursorPageGroupSummary,
JoinGroupRequest, ScanGroupsResult.
"""

from __future__ import annotations

from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import Field, model_validator

from eyenet.contracts.candidate import GroupCandidateRow
from eyenet.contracts.enums import CandidateState, GroupKind

from ._base import ApiSchema
from .pagination import CursorPage

# Candidate state (+ member_dialog) -> operator-facing status.
_STATUS: dict[CandidateState, str] = {
    CandidateState.JOINED: "monitored",
    CandidateState.JOINING: "joining",
    CandidateState.REQUESTED: "requested",
    CandidateState.APPROVED: "approving",
    CandidateState.REJECTED: "rejected",
    CandidateState.FAILED: "failed",
    CandidateState.PARKED: "parked",
}


def _status(row: GroupCandidateRow) -> str:
    if row.state in (CandidateState.DISCOVERED, CandidateState.QUEUED):
        # Direct dialog member vs only reachable via descent.
        return "member_unmonitored" if row.member_dialog else "discovered"
    return _STATUS.get(row.state, row.state.value)


class GroupSummary(ApiSchema):
    """Group-centric projection of a GroupCandidate for GET /v1/groups."""

    candidate_id: UUID
    source_id: UUID
    platform_groupid: str = Field(max_length=512)
    kind: GroupKind | None = None
    title: str | None = None
    status: str = Field(
        description="monitored|joining|requested|approving|member_unmonitored|discovered|rejected|failed|parked"
    )
    member_dialog: bool = False
    score: float = Field(ge=0.0)
    group_id: UUID | None = None
    last_observed_at_ingest: datetime

    @classmethod
    def from_domain(cls, row: GroupCandidateRow) -> GroupSummary:
        return cls(
            candidate_id=row.id,
            source_id=row.source_id,
            platform_groupid=row.platform_groupid,
            kind=row.kind_hint,
            title=row.display_name_hint,
            status=_status(row),
            member_dialog=row.member_dialog,
            score=row.score,
            group_id=row.resulting_group_id,
            last_observed_at_ingest=row.last_observed_at_ingest,
        )


class CursorPageGroupSummary(CursorPage[GroupSummary]):
    """200 page response for GET /v1/groups."""


class JoinGroupRequest(ApiSchema):
    """Body for POST /v1/groups/join — operator-initiated join.

    Target is either an existing candidate (``candidate_id``) or an undiscovered
    group by ``source_id`` + ``platform_groupid`` (a candidate is created). A
    collector is assigned; the supervisor executes the join off-path."""

    collector_id: UUID
    candidate_id: UUID | None = None
    source_id: UUID | None = None
    platform_groupid: str | None = Field(default=None, max_length=512)
    kind: GroupKind | None = None

    @model_validator(mode="after")
    def _exactly_one_target(self) -> Self:
        by_id = self.candidate_id is not None
        by_ref = self.source_id is not None and self.platform_groupid is not None
        if by_id == by_ref:
            raise ValueError("provide either candidate_id, or both source_id and platform_groupid")
        return self


class LeaveGroupRequest(ApiSchema):
    """Body for POST /v1/groups/leave — stop monitoring a joined group.

    Targets the group's candidate; the collector(s) in it leave on the platform,
    the membership is closed, and the candidate is parked."""

    candidate_id: UUID
    reason: str = Field(default="operator_left", min_length=1, max_length=2048)


class ScanGroupsResult(ApiSchema):
    """202 response for POST /v1/groups/scan — how many collectors were signaled."""

    collectors_signaled: int


__all__ = [
    "CursorPageGroupSummary",
    "GroupSummary",
    "JoinGroupRequest",
    "LeaveGroupRequest",
    "ScanGroupsResult",
]
