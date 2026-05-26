"""`SourceDomain` — hostname → Source binding (MODELS §2.26, API_PLAN §4.13).

A SourceDomain is a single hostname pattern that an operator has bound to
a Source. One Source has many SourceDomains; exactly one is the primary
(used for display + canonical_url validation). The table powers two
storage-layer invariants:

* In-transaction overlap detection on insert — refuses ambiguous routing
  before the row lands (see :exc:`SourceDomainOverlapError`).
* Cross-source bridge resolution — when a sensor primitive sees a URL
  whose host matches a primary SourceDomain, the resulting
  InfrastructureArtifact populates ``resolved_to_source_id`` atomically.

Surface: db.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from ._base import DbRowBase
from .enums import SourceDomainPatternKind


class SourceDomainRow(DbRowBase):
    """Persisted SourceDomain (MODELS §2.26).

    ``pattern`` is always stored post-:func:`eyenet.util.domain.normalize_host`
    — lowercase ASCII punycode, no trailing dot, no ``*`` literal. For
    ``subdomain_wildcard`` the pattern holds the parent only (no ``*.``
    prefix); a CHECK at the SQL layer enforces this.

    Soft-deleted via ``removed_at``; the row remains for audit. Re-adding
    the same pattern after removal is allowed (new row, new ``id``, new
    ``created_at``).
    """

    source_id: UUID
    pattern: str = Field(min_length=1, max_length=253)
    pattern_kind: SourceDomainPatternKind
    is_primary: bool = False
    created_at: datetime
    created_by_user_id: UUID | None = None
    removed_at: datetime | None = None
    removed_by_user_id: UUID | None = None
    notes: str | None = Field(default=None, max_length=1024)


__all__ = ["SourceDomainRow"]
