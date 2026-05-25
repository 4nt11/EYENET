"""Backend-neutral storage exceptions + domain constants.

These types are part of the public storage API and intentionally do NOT
live alongside the SQLite impls in `impl/sqlite/` — every backend raises
the same exception type, so it stays at the storage-module root.
"""

from __future__ import annotations

from datetime import timedelta

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


__all__ = [
    "MAX_GRANT_DURATION",
    "CaseError",
    "ClearanceGrantError",
    "ReclassifyDemotionError",
]
