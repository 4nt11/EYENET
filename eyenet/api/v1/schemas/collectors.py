# SPDX-License-Identifier: AGPL-3.0-or-later
"""Collector resource schemas (M9.D2, API_PLAN §3.9 / §4.11).

Projections over :class:`CollectorRow` / :class:`CollectorGroupMembershipRow` /
:class:`CollectorFleetHealth`. ``config`` is redacted for callers without
``read:collectors_config`` via :func:`redact_config` (the §4.11.4 sensitivity
contract). A full Pydantic discriminated-union over ``config`` per ``kind`` is
deferred — ``config`` is validated as an opaque dict carrying its ``kind`` here.

OpenAPI: `contracts/openapi/eyenet.v1.yaml` — Collector*, CollectorMembership,
CollectorFleetHealth, CursorPageCollectorSummary (pinned in slice 4).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from eyenet.contracts.collector import (
    CollectorFleetHealth,
    CollectorRow,
    redact_config,
)
from eyenet.contracts.enums import (
    CollectorDesiredState,
    CollectorObservedState,
    JoinedVia,
    SourceKind,
)
from eyenet.contracts.membership import CollectorGroupMembershipRow

from ._base import ApiSchema
from .pagination import CursorPage


class CollectorSummary(ApiSchema):
    """Projection of MODELS §2.19 Collector for listing. ``config`` redacted
    unless the caller holds ``read:collectors_config``."""

    collector_id: UUID
    instance_name: str = Field(max_length=128)
    kind: SourceKind
    source_id: UUID
    desired_state: CollectorDesiredState
    observed_state: CollectorObservedState
    restart_count: int = Field(ge=0)
    last_heartbeat_at: datetime | None = None
    config: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_domain(cls, row: CollectorRow, *, has_config_grant: bool) -> CollectorSummary:
        return cls(
            collector_id=row.id,
            instance_name=row.instance_name,
            kind=row.kind,
            source_id=row.source_id,
            desired_state=row.desired_state,
            observed_state=row.observed_state,
            restart_count=row.restart_count,
            last_heartbeat_at=row.last_heartbeat_at,
            config=redact_config(row.config, has_read_grant=has_config_grant),
        )


class CollectorDetail(CollectorSummary):
    """Projection for `GET /v1/collectors/{id}` — adds identity + error/audit fields."""

    identity_id: UUID
    last_error_type: str | None = None
    last_error_message: str | None = None
    created_at: datetime
    notes: str | None = None

    @classmethod
    def from_domain_detail(cls, row: CollectorRow, *, has_config_grant: bool) -> CollectorDetail:
        return cls(
            collector_id=row.id,
            instance_name=row.instance_name,
            kind=row.kind,
            source_id=row.source_id,
            desired_state=row.desired_state,
            observed_state=row.observed_state,
            restart_count=row.restart_count,
            last_heartbeat_at=row.last_heartbeat_at,
            config=redact_config(row.config, has_read_grant=has_config_grant),
            identity_id=row.identity_id,
            last_error_type=row.last_error_type,
            last_error_message=row.last_error_message,
            created_at=row.created_at,
            notes=row.notes,
        )


class CollectorMembershipView(ApiSchema):
    """Projection of MODELS §2.22 CollectorGroupMembership."""

    membership_id: UUID
    collector_id: UUID
    group_id: UUID
    joined_at: datetime
    joined_via: JoinedVia
    joined_via_candidate_id: UUID | None = None
    left_at: datetime | None = None
    left_reason: str | None = None

    @classmethod
    def from_domain(cls, row: CollectorGroupMembershipRow) -> CollectorMembershipView:
        return cls(
            membership_id=row.id,
            collector_id=row.collector_id,
            group_id=row.group_id,
            joined_at=row.joined_at,
            joined_via=row.joined_via,
            joined_via_candidate_id=row.joined_via_candidate_id,
            left_at=row.left_at,
            left_reason=row.left_reason,
        )


class CollectorFleetHealthView(ApiSchema):
    """Projection of :class:`CollectorFleetHealth` for `GET /v1/collectors/health`."""

    total: int = Field(ge=0)
    counts_by_observed_state: dict[CollectorObservedState, int] = Field(default_factory=dict)
    oldest_heartbeat_at: datetime | None = None
    restart_storm_leader_id: UUID | None = None
    max_restart_count: int = Field(ge=0)

    @classmethod
    def from_domain(cls, health: CollectorFleetHealth) -> CollectorFleetHealthView:
        return cls(
            total=health.total,
            counts_by_observed_state=health.counts_by_observed_state,
            oldest_heartbeat_at=health.oldest_heartbeat_at,
            restart_storm_leader_id=health.restart_storm_leader_id,
            max_restart_count=health.max_restart_count,
        )


class CreateCollectorRequest(ApiSchema):
    """Body of `POST /v1/collectors`. Leases an Identity (``identity_id`` — one
    collector per Identity, enforced by the DB unique → 409 on reuse)."""

    instance_name: str = Field(min_length=3, max_length=128)
    kind: SourceKind
    source_id: UUID
    identity_id: UUID
    config: dict[str, Any] = Field(default_factory=dict)
    notes: str | None = Field(default=None, max_length=1024)


class UpdateCollectorRequest(ApiSchema):
    """Body of `PATCH /v1/collectors/{id}`. Only fields present are applied
    (``model_fields_set``). ``observed_state`` is never settable (supervisor-only)."""

    config: dict[str, Any] | None = None
    instance_name: str | None = Field(default=None, min_length=3, max_length=128)
    notes: str | None = Field(default=None, max_length=1024)
    desired_state: CollectorDesiredState | None = None


class CursorPageCollectorSummary(CursorPage[CollectorSummary]):
    """200 page response for `GET /v1/collectors`."""


__all__ = [
    "CollectorDetail",
    "CollectorFleetHealthView",
    "CollectorMembershipView",
    "CollectorSummary",
    "CreateCollectorRequest",
    "CursorPageCollectorSummary",
    "UpdateCollectorRequest",
]
