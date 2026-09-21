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
from .enums import (
    ConfidenceTier,
    EngagementScope,
    EngagementSubjectKind,
    IdentityRole,
    IdentityState,
)

SUBJECT_LABEL: str = "identity.label.applied"
SUBJECT_ENGAGEMENT: str = "identity.engagement.authorized"

# Operator identity-action subjects (API_PLAN §3.4, M9.G5). Distinct from the
# `identity.*` label/engagement subjects above — these carry the `eyenet.`
# control-plane prefix.
SUBJECT_IDENTITY_CLAIMED: str = "eyenet.identity.claimed"
SUBJECT_IDENTITY_RELEASED: str = "eyenet.identity.released"
SUBJECT_IDENTITY_FROZEN: str = "eyenet.identity.frozen"
SUBJECT_IDENTITY_BURNED: str = "eyenet.identity.burned"
SUBJECT_IDENTITY_FREEZE_ALL: str = "eyenet.identity.freeze_all"


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
    # Discovery-loop role + graduation (API_PLAN §4.12). The DB identity is the
    # source of truth for role/state/graduation; the file pool stays the
    # credential/session store. The file↔DB provisioning bridge lands with E5.
    role: IdentityRole = IdentityRole.MONITOR
    graduated_at: datetime | None = None
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


# -- Operator identity actions (API_PLAN §3.4, M9.G5) ------------------------


class IdentityActionEnvelope(BusEnvelope):
    """Per-identity operator action. The bus subject
    (`eyenet.identity.{claimed,released,frozen,burned}`) names the action; the
    resulting persisted `new_state` is carried for observers/SSE. The API
    persists `new_state` durably before publishing (documented invariant-#2
    exception — no live identity supervisor yet)."""

    identity_id: UUID
    new_state: IdentityState
    decided_by: str = Field(description="system_user id")
    decided_at: datetime
    reason: str | None = None


class IdentityFreezeAllEnvelope(BusEnvelope):
    """`eyenet.identity.freeze_all` — fleet-wide soft freeze; carries the ids
    actually flipped to FROZEN (terminal identities are left untouched)."""

    frozen_identity_ids: list[UUID] = Field(default_factory=list)
    source_id: UUID | None = None
    decided_by: str = Field(description="system_user id")
    decided_at: datetime
    reason: str | None = None


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
    "SUBJECT_IDENTITY_BURNED",
    "SUBJECT_IDENTITY_CLAIMED",
    "SUBJECT_IDENTITY_FREEZE_ALL",
    "SUBJECT_IDENTITY_FROZEN",
    "SUBJECT_IDENTITY_RELEASED",
    "SUBJECT_LABEL",
    "EngagementAuthorizationEnvelope",
    "EngagementAuthorizationRow",
    "IdentityActionEnvelope",
    "IdentityFreezeAllEnvelope",
    "IdentityLabelEnvelope",
    "IdentityLabelRow",
    "IdentityRow",
]
