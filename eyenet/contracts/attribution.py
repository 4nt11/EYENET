"""Attribution contracts — Profile, Linkage, Persona (MODELS 2.4 to 2.6a).

Bus subjects (PLAN §3):
    attribution.profile.candidate
    attribution.profile.current
    attribution.linkage.proposed

Bus envelopes carry summaries (transport optimization). The persisted row
shapes hold the full state and are the operator's evidence (PLAN §4.3).

LinkageRow invariant (PLAN §5.2 + MODELS §2.5): store the unordered pair as
(actor_a_id, actor_b_id) with `actor_a_id < actor_b_id`. The validator here
is the contract-layer half; the DB-layer CHECK constraint lives in
`eyenet.models.linkage`.

RoleSignal values are engine recipe verdicts, NOT BEHAVE-TEXT primitive
observations. The BEHAVE-TEXT registry has its own `network.governance_role_signal`
and `content.role_signal` primitive enums — these are orthogonal and must not
be conflated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from ._base import BusEnvelope, DbRowBase
from .enums import LinkageState

# -- Role signal type ---------------------------------------------------------

RoleSignal = Literal[
    "lurker_or_observer",
    "bot_or_automated_poster",
    "credential_broker",
    "low_skill_buyer",
    "group_admin",
]
"""Engine-level role verdict. Tighten this set as recipes are calibrated (M5).

NOT a BEHAVE-TEXT primitive. See module docstring.
"""


# -- Recipe result ------------------------------------------------------------


@dataclass(frozen=True)
class RecipeResult:
    """The result of evaluating one recipe against a profile snapshot.

    `reasoning` must include `"calibrated": False` for every uncalibrated
    threshold (see M5). The engine uses this to track which recipes fired and
    with what confidence.
    """

    matches: bool
    confidence: float  # 0..1
    reasoning: dict[str, object] = field(default_factory=dict)


SUBJECT_PROFILE_CANDIDATE: str = "attribution.profile.candidate"
SUBJECT_PROFILE_CURRENT: str = "attribution.profile.current"
SUBJECT_LINKAGE_PROPOSED: str = "attribution.linkage.proposed"
SUBJECT_LINKAGE_SUSPECTED: str = "attribution.linkage.suspected"
SUBJECT_LINKAGE_CONFIRMED: str = "attribution.linkage.confirmed"
SUBJECT_LINKAGE_REJECTED: str = "attribution.linkage.rejected"
SUBJECT_PERSONA_UPDATED: str = "attribution.persona.updated"


# -- Profile ------------------------------------------------------------------


class ProfileSummaryBlock(dict[str, object]):
    """Marker type for `Profile.*_summary` JSON dicts.

    Per PLAN §10 / MODELS §2.4, every summary slot stores
    `last_observation_id` and `derived_from_observation_count` for
    explainability. This is enforced at the engine, not at the contract layer
    — recipes are stable, slot keys are not.
    """


class ProfileCandidateEnvelope(BusEnvelope):
    """`attribution.profile.candidate` — engine-emitted candidate profile."""

    profile_id: UUID
    actor_id: UUID
    version: int
    role_signal: RoleSignal | None = None
    role_confidence: float = Field(ge=0.0, le=1.0)
    derived_at: datetime
    derived_from_observation_count: int


class ProfileCurrentEnvelope(BusEnvelope):
    """`attribution.profile.current` — engine-emitted current best profile."""

    profile_id: UUID
    actor_id: UUID
    version: int
    role_signal: RoleSignal | None = None
    role_confidence: float = Field(ge=0.0, le=1.0)
    stylometric_summary: dict[str, object] = Field(default_factory=dict)
    lexical_summary: dict[str, object] = Field(default_factory=dict)
    temporal_summary: dict[str, object] = Field(default_factory=dict)
    interaction_summary: dict[str, object] = Field(default_factory=dict)
    network_summary: dict[str, object] = Field(default_factory=dict)
    content_summary: dict[str, object] = Field(default_factory=dict)
    derived_at: datetime
    derived_from_observation_count: int


class ProfileRow(DbRowBase):
    """Persisted profile (MODELS §2.4). `is_current` enforced unique-per-actor
    by partial unique index in the SQLModel layer.
    """

    actor_id: UUID
    version: int
    is_current: bool = False
    role_signal: RoleSignal | None = None
    role_confidence: float = Field(ge=0.0, le=1.0)
    stylometric_summary: dict[str, object] = Field(default_factory=dict)
    lexical_summary: dict[str, object] = Field(default_factory=dict)
    temporal_summary: dict[str, object] = Field(default_factory=dict)
    interaction_summary: dict[str, object] = Field(default_factory=dict)
    network_summary: dict[str, object] = Field(default_factory=dict)
    content_summary: dict[str, object] = Field(default_factory=dict)
    derived_at: datetime
    derived_from_observation_count: int


# -- Linkage ------------------------------------------------------------------


def _ordered_pair(a: UUID, b: UUID) -> tuple[UUID, UUID]:
    """Return `(a, b)` with `a < b` per Linkage invariant (PLAN §5.2)."""

    return (a, b) if a < b else (b, a)


class LinkageProposedEnvelope(BusEnvelope):
    """`attribution.linkage.proposed` — linker-emitted link proposal."""

    linkage_id: UUID
    actor_a_id: UUID
    actor_b_id: UUID
    method: str
    score: float = Field(ge=0.0, le=1.0)
    evidence: dict[str, object] = Field(default_factory=dict)
    proposed_at: datetime

    @model_validator(mode="after")
    def _enforce_pair_order(self) -> Self:
        if not self.actor_a_id < self.actor_b_id:
            raise ValueError(
                "LinkageProposedEnvelope requires actor_a_id < actor_b_id; "
                "use LinkageProposedEnvelope.from_pair(a, b, ...) to auto-sort"
            )
        return self

    @classmethod
    def from_pair(
        cls,
        a: UUID,
        b: UUID,
        *,
        linkage_id: UUID,
        method: str,
        score: float,
        evidence: dict[str, object],
        proposed_at: datetime,
        trace_context: object,  # TraceContext, but avoid circular hint
    ) -> Self:
        ordered_a, ordered_b = _ordered_pair(a, b)
        return cls(
            linkage_id=linkage_id,
            actor_a_id=ordered_a,
            actor_b_id=ordered_b,
            method=method,
            score=score,
            evidence=evidence,
            proposed_at=proposed_at,
            trace_context=trace_context,  # type: ignore[arg-type]
        )


class LinkageRow(DbRowBase):
    """Persisted linkage. `actor_a_id < actor_b_id` invariant enforced both
    here and at the DB layer (MODELS §2.5, PLAN §5.2).
    """

    actor_a_id: UUID
    actor_b_id: UUID
    state: LinkageState = LinkageState.PROPOSED
    method: str
    score: float = Field(ge=0.0, le=1.0)
    evidence: dict[str, object] = Field(default_factory=dict)
    proposed_at: datetime
    decided_at: datetime | None = None
    decided_by: str | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _enforce_pair_order(self) -> Self:
        if not self.actor_a_id < self.actor_b_id:
            raise ValueError(
                "LinkageRow requires actor_a_id < actor_b_id; use LinkageRow.from_pair(...)"
            )
        return self

    @classmethod
    def from_pair(
        cls,
        a: UUID,
        b: UUID,
        *,
        method: str,
        score: float,
        evidence: dict[str, object],
        proposed_at: datetime,
        state: LinkageState = LinkageState.PROPOSED,
        decided_at: datetime | None = None,
        decided_by: str | None = None,
        notes: str | None = None,
    ) -> Self:
        ordered_a, ordered_b = _ordered_pair(a, b)
        return cls(
            actor_a_id=ordered_a,
            actor_b_id=ordered_b,
            state=state,
            method=method,
            score=score,
            evidence=evidence,
            proposed_at=proposed_at,
            decided_at=decided_at,
            decided_by=decided_by,
            notes=notes,
        )


# -- Linkage decision envelopes -----------------------------------------------


class _LinkageDecisionBase(BusEnvelope):
    """Shared fields for operator-decision envelopes."""

    linkage_id: UUID
    actor_a_id: UUID
    actor_b_id: UUID
    decided_by: str
    decided_at: datetime
    notes: str | None = None

    @model_validator(mode="after")
    def _enforce_pair_order(self) -> Self:
        if not self.actor_a_id < self.actor_b_id:
            raise ValueError(
                f"{type(self).__name__} requires actor_a_id < actor_b_id; "
                "use from_pair() to auto-sort"
            )
        return self

    @classmethod
    def from_pair(
        cls,
        a: UUID,
        b: UUID,
        *,
        linkage_id: UUID,
        decided_by: str,
        decided_at: datetime,
        notes: str | None = None,
        trace_context: object,
    ) -> Self:
        ordered_a, ordered_b = _ordered_pair(a, b)
        return cls(
            linkage_id=linkage_id,
            actor_a_id=ordered_a,
            actor_b_id=ordered_b,
            decided_by=decided_by,
            decided_at=decided_at,
            notes=notes,
            trace_context=trace_context,  # type: ignore[arg-type]
        )


class LinkageSuspectedEnvelope(_LinkageDecisionBase):
    """`attribution.linkage.suspected` — operator triage promotion."""


class LinkageConfirmedEnvelope(_LinkageDecisionBase):
    """`attribution.linkage.confirmed` — operator confirm; drives Persona aggregation."""


class LinkageRejectedEnvelope(_LinkageDecisionBase):
    """`attribution.linkage.rejected` — operator reject; terminal."""


# -- Persona update envelope --------------------------------------------------


class PersonaChangeKind(StrEnum):
    CREATED = "created"
    MEMBERS_ADDED = "members_added"
    MEMBERS_REMOVED = "members_removed"
    MERGED_WITH = "merged_with"
    SPLIT_FROM = "split_from"


class PersonaUpdatedEnvelope(BusEnvelope):
    """`attribution.persona.updated` — emitted by Graph on every Persona mutation."""

    persona_id: UUID
    member_actor_ids: list[UUID] = Field(default_factory=list)
    change_kind: PersonaChangeKind
    via_linkage_id: UUID | None = None
    at: datetime


# -- Persona / cluster --------------------------------------------------------


class PersonaRow(DbRowBase):
    """Cross-platform identity cluster (MODELS §2.6).

    `member_actor_ids` is the denormalized FORWARD view (cheap reads given
    `persona_id`). Reverse lookups (`actor_id → persona_id`) MUST go through
    `PersonaMembershipRow`. Both views are kept in sync by the same
    transaction.
    """

    label: str | None = None
    member_actor_ids: list[UUID] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class PersonaMembershipRow(DbRowBase):
    """Indexed reverse view of Persona membership (MODELS §2.6a).

    Composite PK on `(persona_id, actor_id)` lives in the SQLModel layer;
    here we just enforce the value invariant (actor belongs to AT MOST one
    persona at a time) at the storage layer via the unique index on
    `actor_id`.
    """

    persona_id: UUID
    actor_id: UUID
    joined_at: datetime
    via_linkage_id: UUID | None = None


__all__ = [
    "SUBJECT_LINKAGE_CONFIRMED",
    "SUBJECT_LINKAGE_PROPOSED",
    "SUBJECT_LINKAGE_REJECTED",
    "SUBJECT_LINKAGE_SUSPECTED",
    "SUBJECT_PERSONA_UPDATED",
    "SUBJECT_PROFILE_CANDIDATE",
    "SUBJECT_PROFILE_CURRENT",
    "LinkageConfirmedEnvelope",
    "LinkageProposedEnvelope",
    "LinkageRejectedEnvelope",
    "LinkageRow",
    "LinkageSuspectedEnvelope",
    "PersonaChangeKind",
    "PersonaMembershipRow",
    "PersonaRow",
    "PersonaUpdatedEnvelope",
    "ProfileCandidateEnvelope",
    "ProfileCurrentEnvelope",
    "ProfileRow",
    "ProfileSummaryBlock",
    "RecipeResult",
    "RoleSignal",
]
