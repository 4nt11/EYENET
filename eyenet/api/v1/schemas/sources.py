# SPDX-License-Identifier: AGPL-3.0-or-later
"""Source + SourceDomain resource schemas (M9.D1, API_PLAN §3.8 / §4.13).

Projections (§9.5) over :class:`SourceRow` / :class:`SourceDomainRow` /
:class:`SourceBridgeSummary`. ``pattern`` + ``pattern_kind`` are immutable
post-create (remove + re-add to preserve the audit trail), so the update
request omits them.

OpenAPI: `contracts/openapi/eyenet.v1.yaml` — Source*, SourceDomain*,
SourceBridgeSummary, CursorPageSourceSummary (pinned in slice 4).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from eyenet.contracts.enums import SourceDomainPatternKind, SourceKind
from eyenet.contracts.source import SourceBridgeSummary, SourceRow
from eyenet.contracts.source_domain import SourceDomainRow

from ._base import ApiSchema
from .pagination import CursorPage


class SourceDomainView(ApiSchema):
    """Projection of MODELS §2.26 SourceDomain for read surfaces."""

    domain_id: UUID
    source_id: UUID
    pattern: str = Field(max_length=253)
    pattern_kind: SourceDomainPatternKind
    is_primary: bool
    created_at: datetime
    removed_at: datetime | None = None
    notes: str | None = None

    @classmethod
    def from_domain(cls, row: SourceDomainRow) -> SourceDomainView:
        return cls(
            domain_id=row.id,
            source_id=row.source_id,
            pattern=row.pattern,
            pattern_kind=row.pattern_kind,
            is_primary=row.is_primary,
            created_at=row.created_at,
            removed_at=row.removed_at,
            notes=row.notes,
        )


class SourceSummary(ApiSchema):
    """Projection of MODELS §1.1 Source for listing (§3.8 — carries the
    count of active SourceDomains per row)."""

    source_id: UUID
    kind: SourceKind
    display_name: str = Field(max_length=512)
    canonical_url: str | None = None
    created_at: datetime
    active_domain_count: int = Field(ge=0)

    @classmethod
    def from_domain(cls, row: SourceRow, *, active_domain_count: int) -> SourceSummary:
        return cls(
            source_id=row.id,
            kind=row.kind,
            display_name=row.display_name,
            canonical_url=row.canonical_url,
            created_at=row.created_at,
            active_domain_count=active_domain_count,
        )


class SourceDetail(SourceSummary):
    """Projection for `GET /v1/sources/{id}` — domains inlined + artifact count."""

    notes: str | None = None
    domains: list[SourceDomainView] = Field(default_factory=list)
    resolved_artifact_count: int = Field(ge=0)


class BridgeSummary(ApiSchema):
    """Projection of :class:`SourceBridgeSummary` for `/v1/sources/{id}/bridge-summary`."""

    source_id: UUID
    resolved: int = Field(ge=0)
    unresolved: int = Field(ge=0)
    ambiguous: int = Field(ge=0)
    not_applicable: int = Field(ge=0)

    @classmethod
    def from_domain(cls, summary: SourceBridgeSummary) -> BridgeSummary:
        return cls(
            source_id=summary.source_id,
            resolved=summary.resolved,
            unresolved=summary.unresolved,
            ambiguous=summary.ambiguous,
            not_applicable=summary.not_applicable,
        )


class CreateSourceRequest(ApiSchema):
    """Body of `POST /v1/sources`.

    Atomic initial-``domains`` bulk-add (§3.8) is deferred: ``add_source_domain``
    commits per call, so a mid-list overlap would leave a half-built Source —
    exactly the state §3.8's rationale warns against. Add domains individually
    via `POST /v1/sources/{id}/domains` until an atomic bulk-add lands. Create
    is upsert-by-(kind, display_name): a duplicate returns the existing row.
    """

    kind: SourceKind
    display_name: str = Field(min_length=1, max_length=512)
    notes: str | None = Field(default=None, max_length=2048)


class UpdateSourceRequest(ApiSchema):
    """Body of `PATCH /v1/sources/{id}`. All fields optional; only the fields
    present in the request are applied (``model_fields_set``). ``canonical_url``
    may be sent as null to clear it."""

    display_name: str | None = Field(default=None, min_length=1, max_length=512)
    canonical_url: str | None = Field(default=None, max_length=2048)
    notes: str | None = Field(default=None, max_length=2048)


class AddSourceDomainRequest(ApiSchema):
    """Body of `POST /v1/sources/{id}/domains`."""

    pattern: str = Field(min_length=1, max_length=253)
    pattern_kind: SourceDomainPatternKind
    is_primary: bool = False
    notes: str | None = Field(default=None, max_length=2048)


class UpdateSourceDomainRequest(ApiSchema):
    """Body of `PATCH /v1/sources/{id}/domains/{domain_id}`.

    ``pattern`` + ``pattern_kind`` are immutable post-create (remove + re-add
    instead). ``is_primary: true`` triggers a primary swap. Notes editing is
    deferred — remove + re-add preserves the audit trail (the §2.26 preference).
    """

    is_primary: bool | None = None


class CursorPageSourceSummary(CursorPage[SourceSummary]):
    """200 page response for `GET /v1/sources`."""


__all__ = [
    "AddSourceDomainRequest",
    "BridgeSummary",
    "CreateSourceRequest",
    "CursorPageSourceSummary",
    "SourceDetail",
    "SourceDomainView",
    "SourceSummary",
    "UpdateSourceDomainRequest",
    "UpdateSourceRequest",
]
