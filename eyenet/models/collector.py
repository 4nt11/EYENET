"""CollectorTable — the persisted collector row (API_PLAN §4.11, MODELS §2.19).

A ``Collector`` row binds:

* a :class:`SourceTable` (which platform — telegram / matrix / ...)
* an :class:`IdentityTable` (which credential — leased exclusively;
  the unique constraint on ``identity_id`` is the durable truth that
  no two collectors share an Identity)
* a ``kind``-discriminated ``config`` JSON blob (which chats/rooms,
  rate caps, proxy overrides — validated against a Pydantic
  discriminated union at the API layer, M9.D2)
* an operator-expressed ``desired_state`` (running / stopped / disabled)
* a supervisor-reported ``observed_state``
  (stopped / starting / running / cooling / crashed)

This file is storage shape only. The supervisor that reconciles
``desired_state`` → ``observed_state`` lands in M9.E3
(:class:`eyenet.services.collector_supervisor.CollectorSupervisor`).
The HTTP surface that mutates desired-state on the operator's behalf
lands in M9.D2.

Hard delete (not soft) — :class:`CollectorTable` has no ``removed_at``.
The API layer (M9.D2) gates ``DELETE`` on
``observed_state == stopped``; live deletion is refused there, not here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, CheckConstraint, Column
from sqlmodel import Field, SQLModel

from eyenet.contracts.enums import (
    CollectorDesiredState,
    CollectorObservedState,
    SourceKind,
)

from ._base import new_uuid7


class CollectorTable(SQLModel, table=True):
    """`collector` — operator-managed runtime fleet row (API_PLAN §4.11)."""

    __tablename__ = "collector"
    __table_args__ = (
        CheckConstraint(
            "desired_state IN ('RUNNING', 'STOPPED', 'DISABLED')",
            name="ck_collector_desired_state",
        ),
        CheckConstraint(
            "observed_state IN ('STOPPED', 'STARTING', 'RUNNING', 'COOLING', 'CRASHED')",
            name="ck_collector_observed_state",
        ),
        CheckConstraint(
            "restart_count >= 0",
            name="ck_collector_restart_count_nonneg",
        ),
        CheckConstraint("length(instance_name) >= 3", name="ck_collector_instance_name_min"),
        # last_error_type and last_error_message are a pair: both NULL or both set.
        # Populated when observed_state transitions to 'CRASHED'; cleared on
        # next successful start.
        CheckConstraint(
            "(last_error_type IS NULL AND last_error_message IS NULL) "
            "OR (last_error_type IS NOT NULL AND last_error_message IS NOT NULL)",
            name="ck_collector_last_error_pair",
        ),
    )

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    # Operator-facing label — globally unique so it can appear in
    # SystemLog rows and audit subjects without ambiguity.
    instance_name: str = Field(unique=True, index=True, max_length=128)
    kind: SourceKind = Field(index=True)
    source_id: UUID = Field(foreign_key="source.id", index=True)
    # One identity per collector — the durable truth that prevents two
    # logged-in sessions on the same account (API_PLAN §4.11.3).
    identity_id: UUID = Field(foreign_key="identity.id", unique=True, index=True)
    # Discriminated-union config blob (validated at the API layer per
    # API_PLAN §4.11.4). Stored opaquely here; redaction for callers
    # without ``read:collectors_config`` is also an API-layer concern
    # (see ``eyenet.contracts.collector.redact_config``).
    config: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    desired_state: CollectorDesiredState = Field(default=CollectorDesiredState.STOPPED)
    observed_state: CollectorObservedState = Field(default=CollectorObservedState.STOPPED)
    # Drives exponential backoff: cooling window = min(2^restart_count, 600) sec.
    restart_count: int = Field(default=0)
    last_heartbeat_at: datetime | None = None
    last_error_type: str | None = Field(default=None, max_length=128)
    last_error_message: str | None = Field(default=None, max_length=4096)
    created_at: datetime
    created_by_user_id: UUID = Field(foreign_key="system_user.id")
    notes: str | None = Field(default=None, max_length=1024)


__all__ = ["CollectorTable"]
