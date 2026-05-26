"""Backend-neutral storage exceptions + domain constants.

These types are part of the public storage API and intentionally do NOT
live alongside the SQLite impls in `impl/sqlite/` — every backend raises
the same exception type, so it stays at the storage-module root.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

MAX_GRANT_DURATION = timedelta(days=90)


class ClearanceGrantError(Exception):
    """Helper-layer rejection of a malformed grant or revocation.

    Schema CHECK is the dialect-level backstop; this exception fires
    earlier so the API layer can render a domain-shaped 4xx body.
    """


class CaseError(Exception):
    """Domain-shaped rejection from the case-store helper layer."""


class ReclassifyDemotionError(Exception):
    """Raised when a reclassify call attempts to lower a row's tier.

    Storage CHECK is the dialect-level backstop; this exception fires
    first so the API can produce a 422 and so the rejection itself lands
    in the audit trail as `reclassify.rejected`.
    """


class SourceDomainOverlapError(Exception):
    """In-transaction overlap rejection from ``add_source_domain`` (MODELS §2.26).

    Raised before INSERT when the candidate ``(pattern, pattern_kind)``
    can match any hostname also matched by an existing non-removed
    SourceDomain row. The conflict is global across all Sources — a
    wildcard belonging to Source A blocks Source B's exact in the same
    DNS region (no ambiguous routing).

    ``conflicting_id`` and ``conflict_kind`` give the API layer enough to
    build the 409 problem-details body without re-querying.
    """

    def __init__(self, conflicting_id: UUID, conflict_kind: str) -> None:
        self.conflicting_id = conflicting_id
        self.conflict_kind = conflict_kind
        super().__init__(
            f"source_domain overlaps existing {conflict_kind} row "
            f"({conflicting_id})"
        )


__all__ = [
    "MAX_GRANT_DURATION",
    "CaseError",
    "ClearanceGrantError",
    "ReclassifyDemotionError",
    "SourceDomainOverlapError",
]
