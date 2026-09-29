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
from eyenet.contracts.incident import IncidentLabelRow, MessageGeoRow
from eyenet.models.group import GroupTable
from eyenet.models.message import MessageTable

from ._base import ApiSchema
from .pagination import CursorPage


def _s(value: object) -> str | None:
    return str(value) if value is not None else None


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


class GroupMessage(ApiSchema):
    """One message in a group (forum thread / chat) — for the raw reader."""

    id: UUID
    evidence_ref: str
    platform_msgid: str
    ts: datetime
    author_display: str | None = None
    author_username: str | None = None
    body: str
    body_html: str | None = None
    reply_gated: bool = False
    edited: bool = False
    has_attachment: bool = False
    incident_labels: list[str] = Field(default_factory=list)  # classifier verdict, if any
    corrected_labels: list[str] | None = None  # operator ground-truth (None = uncorrected)
    corrected_by: str | None = None
    corrected_at: datetime | None = None
    victim_country: str | None = Field(
        default=None,
        min_length=2,
        max_length=2,
        description="WHERE (victim): ISO 3166-1 alpha-2; None if unknown/mixed/unattributed.",
    )

    @classmethod
    def from_message(
        cls,
        msg: MessageTable,
        incident_labels: list[str] | None = None,
        correction: IncidentLabelRow | None = None,
        geo: MessageGeoRow | None = None,
    ) -> GroupMessage:
        ss = msg.source_specific or {}
        return cls(
            id=msg.id,
            evidence_ref=msg.evidence_ref,
            platform_msgid=msg.platform_msgid,
            ts=msg.sent_at_source,
            author_display=_s(ss.get("author_display")),
            author_username=_s(ss.get("author_username")),
            body=msg.body,
            body_html=_s(ss.get("body_html")),
            reply_gated=bool(ss.get("reply_gated", False)),
            edited=bool(ss.get("edited", False)),
            has_attachment=msg.has_attachment,
            incident_labels=incident_labels or [],
            corrected_labels=list(correction.labels) if correction is not None else None,
            corrected_by=correction.decided_by if correction is not None else None,
            corrected_at=correction.decided_at if correction is not None else None,
            victim_country=geo.country if geo is not None else None,
        )


class CursorPageGroupMessage(CursorPage[GroupMessage]):
    """200 page response for `GET /v1/groups/{group_id}/messages`."""


class GroupThread(ApiSchema):
    """A forum thread under a category — the reader's thread-list row."""

    group_id: UUID
    platform_groupid: str
    title: str | None = None
    last_observed_at: datetime

    @classmethod
    def from_group(cls, g: GroupTable) -> GroupThread:
        return cls(
            group_id=g.id,
            platform_groupid=g.platform_groupid,
            title=g.current_title,
            last_observed_at=g.last_observed_at_ingest,
        )


class CursorPageGroupThread(CursorPage[GroupThread]):
    """200 page response for `GET /v1/groups/{category_id}/threads`."""


class CategorySearchHit(ApiSchema):
    """One body-search match inside a forum category, tagged with the thread it came
    from — the reader's category-level search result (links back to that thread)."""

    id: UUID
    ts: datetime
    author_display: str | None = None
    body: str
    thread_group_id: UUID
    thread_title: str | None = None

    @classmethod
    def from_row(
        cls, msg: MessageTable, thread_group_id: UUID, thread_title: str | None
    ) -> CategorySearchHit:
        ss = msg.source_specific or {}
        return cls(
            id=msg.id,
            ts=msg.sent_at_source,
            author_display=_s(ss.get("author_display")),
            body=msg.body,
            thread_group_id=thread_group_id,
            thread_title=thread_title,
        )


class CursorPageCategorySearchHit(CursorPage[CategorySearchHit]):
    """200 page response for `GET /v1/groups/{category_id}/search`."""


class ForumReplyRequest(ApiSchema):
    """Body for POST /v1/groups/{group_id}/reply — the operator's typed reply.

    Replying unlocks a MyBB [hide] gate. The text is verbatim operator input,
    never auto-generated; the collector posts exactly this."""

    message: str = Field(min_length=1, max_length=10_000)


class ForumReplyResult(ApiSchema):
    """202 response — the reply was queued for the collector to post under throttle."""

    request_id: UUID
    state: str


__all__ = [
    "CategorySearchHit",
    "CursorPageCategorySearchHit",
    "CursorPageGroupMessage",
    "CursorPageGroupSummary",
    "CursorPageGroupThread",
    "ForumReplyRequest",
    "ForumReplyResult",
    "GroupMessage",
    "GroupSummary",
    "GroupThread",
    "JoinGroupRequest",
    "LeaveGroupRequest",
    "ScanGroupsResult",
]
