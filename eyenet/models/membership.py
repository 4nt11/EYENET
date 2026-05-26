"""CollectorGroupMembershipTable + MessageObservationTable (MODELS §2.22-2.23, M9.C5).

CollectorGroupMembership tracks which operator-controlled collectors are (or
were) in which groups. Distinct from the actor-group Membership table in
social_graph.py, which tracks observed platform actors.

Row lifecycle: ``open_membership`` inserts with ``left_at=None``; the
application enforces exactly one active row per (collector, group) via a
SELECT-before-INSERT guard. On departure, ``close_membership`` sets
``left_at`` + ``left_reason`` without deleting — rows are retained for
OPSEC tracing ("which collector was in group X at time T?").

Re-joining after ban creates a new row (``joined_via=RESTORED``); the
old row has ``left_reason='banned'``.

MessageObservation records that a specific collector observed a specific
message. Composite PK (message_id, collector_id) — exactly one row per
(message, collector) pair. ``was_first_sighting`` is determined atomically
at INSERT time by whether any prior observation row exists for that message_id.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CHAR, CheckConstraint, Column, Computed, Index, UniqueConstraint
from sqlmodel import Field, SQLModel

from eyenet.contracts.enums import JoinedVia

from ._base import new_uuid7


class CollectorGroupMembershipTable(SQLModel, table=True):
    """`collector_group_membership` — collector ↔ group membership log (MODELS §2.22)."""

    __tablename__ = "collector_group_membership"
    __table_args__ = (
        CheckConstraint(
            "joined_via IN ('SEED','CANDIDATE','MANUAL','RESTORED')",
            name="ck_membership_joined_via",
        ),
        CheckConstraint(
            "(joined_via = 'CANDIDATE' AND joined_via_candidate_id IS NOT NULL) "
            "OR (joined_via != 'CANDIDATE' AND joined_via_candidate_id IS NULL)",
            name="ck_membership_candidate_fk_paired",
        ),
        Index("ix_membership_group_left", "group_id", "left_at"),
        Index("ix_membership_collector_left", "collector_id", "left_at"),
    )

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    collector_id: UUID = Field(foreign_key="collector.id", index=True)
    group_id: UUID = Field(foreign_key="group_.id", index=True)
    joined_at: datetime
    joined_via: JoinedVia
    joined_via_candidate_id: UUID | None = Field(default=None, foreign_key="group_candidate.id")
    left_at: datetime | None = None
    # 'operator_stop' | 'banned' | 'identity_burned' | 'policy_eviction' | 'failed'
    left_reason: str | None = Field(default=None, max_length=64)


class MessageObservationTable(SQLModel, table=True):
    """`message_observation` — which collector observed which message (MODELS §2.23).

    Composite PK (message_id, collector_id): exactly one row per (message,
    collector) pair.

    ``was_first_sighting`` is set atomically via the generated column
    ``first_sighting_claim``: it holds ``message_id`` (as hex text) when
    ``was_first_sighting = TRUE``, NULL otherwise. The UNIQUE constraint on
    ``first_sighting_claim`` makes the INSERT itself the atomic claim —
    at most one row per message_id can carry ``was_first_sighting=TRUE``.
    ``record_observation`` tries TRUE first; if IntegrityError fires (another
    collector already claimed first-sighting), it retries with FALSE.
    """

    __tablename__ = "message_observation"
    __table_args__ = (
        # Exactly one first-sighting row per message_id, enforced at INSERT.
        UniqueConstraint("first_sighting_claim", name="uq_obs_first_sighting_per_message"),
        Index("ix_obs_collector_ingest", "collector_id", "observed_at_ingest"),
        Index("ix_obs_collector_first_sighting", "collector_id", "was_first_sighting"),
    )

    message_id: UUID = Field(foreign_key="message.id", primary_key=True)
    collector_id: UUID = Field(foreign_key="collector.id", primary_key=True)
    observed_at_ingest: datetime
    was_first_sighting: bool = False
    # Generated column: non-NULL only when was_first_sighting=TRUE so the
    # UNIQUE constraint lets at most one row claim first-sighting per message.
    first_sighting_claim: str | None = Field(
        default=None,
        sa_column=Column(
            "first_sighting_claim",
            CHAR(32),
            Computed(
                "CASE WHEN was_first_sighting THEN hex(message_id) ELSE NULL END",
                persisted=True,
            ),
        ),
    )


__all__ = ["CollectorGroupMembershipTable", "MessageObservationTable"]
