"""Operator identity & authorization contracts.

- `IdentityRow` — operator persona used to observe (MODELS §2.1). DB-only.
  Credentials NEVER ride the bus (PLAN §4.3).
- `IdentityLabelEnvelope` / `IdentityLabelRow` — operator-supplied
  ground-truth labels on actors (MODELS §2.12). bus+db.
- `EngagementAuthorizationEnvelope` / `EngagementAuthorizationRow` —
  authorized engagement scope on actor or group (MODELS §2.13). bus+db.

Subjects: `identity.label.applied`, `identity.engagement.authorized`
(PLAN §3).
"""

from __future__ import annotations

from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import Field, model_validator

from ._base import BusEnvelope, DbRowBase
from .enums import ConfidenceTier, EngagementScope, EngagementSubjectKind, IdentityState

SUBJECT_LABEL: str = "identity.label.applied"
SUBJECT_ENGAGEMENT: str = "identity.engagement.authorized"


# -- Operator persona ---------------------------------------------------------


class IdentityRow(DbRowBase):
    """Operator persona — encrypted at rest. NEVER on the bus."""

    name: str = Field(description="e.g. tg_alpha, forum_lurker_03")
    source_id: UUID
    session_path: str = Field(description="path to encrypted session blob on disk")
    proxy_uri: str | None = None
    cooldown_seconds: int = Field(default=21_600, description="default 6h between sessions")
    last_used_at: datetime | None = None
    state: IdentityState = IdentityState.AVAILABLE
    notes: str | None = None


# -- Identity labels (ground truth) ------------------------------------------


class _IdentityLabelFields:
    """Shared field shape between envelope and row."""


class IdentityLabelEnvelope(BusEnvelope):
    """`identity.label.applied` — operator-supplied ground truth (MODELS §2.12)."""

    label_id: UUID
    actor_id: UUID
    label: str = Field(description="free-form or recipe-aligned (e.g. credential_broker)")
    confidence: ConfidenceTier
    applied_by: str = Field(description="system_user id")
    applied_at: datetime
    rationale: str


class IdentityLabelRow(DbRowBase):
    """Persisted identity label."""

    actor_id: UUID
    label: str
    confidence: ConfidenceTier
    applied_by: str
    applied_at: datetime
    rationale: str


# -- Engagement authorization ------------------------------------------------


class EngagementAuthorizationEnvelope(BusEnvelope):
    """`identity.engagement.authorized` (MODELS §2.13).

    Discriminated on `subject_kind`: exactly one of `actor_id` / `group_id`
    must be set. Enforced both here and at the DB layer (CHECK constraint
    in `eyenet.models.identity`).
    """

    auth_id: UUID
    subject_kind: EngagementSubjectKind
    actor_id: UUID | None = None
    group_id: UUID | None = None
    authorized_by: str = Field(description="system_user id")
    authorized_at: datetime
    scope: EngagementScope
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def _exactly_one_of_actor_or_group(self) -> Self:
        actor_set = self.actor_id is not None
        group_set = self.group_id is not None
        if actor_set == group_set:
            raise ValueError("EngagementAuthorization requires exactly one of actor_id/group_id")
        if self.subject_kind == EngagementSubjectKind.ACTOR and not actor_set:
            raise ValueError("subject_kind=actor requires actor_id")
        if self.subject_kind == EngagementSubjectKind.GROUP and not group_set:
            raise ValueError("subject_kind=group requires group_id")
        return self


class EngagementAuthorizationRow(DbRowBase):
    """Persisted engagement authorization."""

    subject_kind: EngagementSubjectKind
    actor_id: UUID | None = None
    group_id: UUID | None = None
    authorized_by: str
    authorized_at: datetime
    scope: EngagementScope
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def _exactly_one_of_actor_or_group(self) -> Self:
        actor_set = self.actor_id is not None
        group_set = self.group_id is not None
        if actor_set == group_set:
            raise ValueError("EngagementAuthorization requires exactly one of actor_id/group_id")
        if self.subject_kind == EngagementSubjectKind.ACTOR and not actor_set:
            raise ValueError("subject_kind=actor requires actor_id")
        if self.subject_kind == EngagementSubjectKind.GROUP and not group_set:
            raise ValueError("subject_kind=group requires group_id")
        return self


__all__ = [
    "SUBJECT_ENGAGEMENT",
    "SUBJECT_LABEL",
    "EngagementAuthorizationEnvelope",
    "EngagementAuthorizationRow",
    "IdentityLabelEnvelope",
    "IdentityLabelRow",
    "IdentityRow",
]
