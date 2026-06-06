"""GroupCandidateTable + GroupCandidateMentionTable (MODELS §2.20-2.21, API_PLAN §4.12).

GroupCandidate is the "waiting room" for discovered groups — one row per
(source_id, platform_groupid), global across all collectors. State machine:

    discovered → queued → approved → joining → joined
                  │           │          │
                  ↓           ↓          ↓
               rejected    rejected   failed
                  │                     │
                  └──── parked ──────────┘

GroupCandidateMention is the provenance trail: one row per signal that points
to a candidate. Multiple collectors can record the same platform mention; each
gets its own row. The (candidate_id, mention_evidence_ref) UNIQUE constraint
makes re-insertion of the same platform event idempotent.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, CheckConstraint, Column, Index, UniqueConstraint
from sqlmodel import Field, SQLModel

from eyenet.contracts.enums import CandidateState, GroupKind, MentionKind

from ._base import new_uuid7


class GroupCandidateTable(SQLModel, table=True):
    """`group_candidate` — cross-reference discovery queue row (MODELS §2.20)."""

    __tablename__ = "group_candidate"
    __table_args__ = (
        UniqueConstraint("source_id", "platform_groupid", name="uq_candidate_source_platform"),
        CheckConstraint(
            "state IN ('DISCOVERED','QUEUED','APPROVED','JOINING',"
            "'JOINED','REQUESTED','REJECTED','FAILED','PARKED')",
            name="ck_candidate_state",
        ),
        CheckConstraint("score >= 0.0", name="ck_candidate_score_nonneg"),
        CheckConstraint("score_function_version >= 1", name="ck_candidate_score_fn_version"),
        Index("ix_candidate_state_score", "state", "score"),
        Index("ix_candidate_assigned_state", "assigned_collector_id", "state"),
    )

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    source_id: UUID = Field(foreign_key="source.id", index=True)
    platform_groupid: str = Field(max_length=512)
    kind_hint: GroupKind | None = Field(default=None)
    display_name_hint: str | None = Field(default=None, max_length=512)
    state: CandidateState = Field(default=CandidateState.DISCOVERED)
    score: float = Field(default=0.0)
    score_breakdown: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    score_function_version: int = Field(default=1)
    first_observed_at_ingest: datetime
    last_observed_at_ingest: datetime
    reviewed_at: datetime | None = None
    reviewed_by: str | None = Field(default=None, max_length=256)
    rejection_reason: str | None = Field(default=None, max_length=2048)
    assigned_collector_id: UUID | None = Field(default=None, foreign_key="collector.id")
    resulting_group_id: UUID | None = Field(default=None, foreign_key="group_.id")


class GroupCandidateMentionTable(SQLModel, table=True):
    """`group_candidate_mention` — provenance trail for a GroupCandidate (MODELS §2.21).

    The UNIQUE on (candidate_id, mention_evidence_ref) makes the record_candidate_mention
    storage call idempotent: the same platform event (same message, same signal) can
    only produce one mention row per candidate, regardless of how many times the
    collector re-emits it.
    """

    __tablename__ = "group_candidate_mention"
    __table_args__ = (
        UniqueConstraint(
            "candidate_id",
            "mention_evidence_ref",
            name="uq_mention_candidate_evidence",
        ),
        CheckConstraint("depth_from_root >= 0", name="ck_mention_depth_nonneg"),
        CheckConstraint(
            "mention_kind IN ('INVITE_LINK','USERNAME_MENTION','FORWARD_ORIGIN',"
            "'LINK_PREVIEW','BIO_LINK','OTHER')",
            name="ck_mention_kind",
        ),
        Index("ix_mention_candidate_depth", "candidate_id", "depth_from_root"),
        Index("ix_mention_collector_ingest", "observed_by_collector_id", "mentioned_at_ingest"),
        Index("ix_mention_seed_root", "seed_root_id"),
    )

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    candidate_id: UUID = Field(foreign_key="group_candidate.id", index=True)
    observed_by_collector_id: UUID = Field(foreign_key="collector.id")
    observed_in_group_id: UUID = Field(foreign_key="group_.id")
    seed_root_id: UUID | None = Field(default=None, foreign_key="group_.id")
    depth_from_root: int = Field(default=0)
    # "telegram:<chat_id>:<msg_id>", "matrix:<room_id>:<event_id>", etc.
    mention_evidence_ref: str = Field(max_length=512)
    mention_kind: MentionKind
    mentioned_at_source: datetime
    mentioned_at_ingest: datetime
    mentioning_actor_id: UUID = Field(foreign_key="actor.id")
    mentioning_actor_role_signal: str | None = Field(default=None, max_length=128)


__all__ = ["GroupCandidateMentionTable", "GroupCandidateTable"]
