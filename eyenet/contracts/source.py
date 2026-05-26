"""`Source` contract — a specific platform origin (MODELS §1.1).

Telegram has one Source row; each forum domain is its own Source row.
NEVER carries credentials — those live on `Identity` (MODELS §2.1).

Surface: db (no SUBJECT exported).
"""

from __future__ import annotations

from datetime import datetime

from ._base import DbRowBase
from .enums import SourceKind


class SourceRow(DbRowBase):
    """Persisted Source row (MODELS §1.1).

    ``canonical_url`` is display-only — when set, the host portion must
    match the Source's primary :class:`SourceDomainRow` pattern. The
    storage layer enforces this via ``set_source_canonical_url`` (M9.C2).
    """

    kind: SourceKind
    display_name: str
    canonical_url: str | None = None
    created_at: datetime
    notes: str | None = None


__all__ = ["SourceRow"]
