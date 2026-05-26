"""SourceDomainTable — hostname patterns bound to Sources (MODELS §2.26).

The table powers two storage-layer invariants documented in
``development/MODELS.md`` §2.25 + §2.26 and codified in
:class:`eyenet.storage.sqlmodel_repo.sources.SourcesMixin`:

* In-transaction overlap detection on every insert (refuses ambiguous
  routing before the row lands).
* The display-only ``Source.canonical_url`` validation (M9.C2) and the
  cross-source bridge resolution Path A / Path B (M9.C6) read from this
  table.

``pattern`` is always stored post-:func:`eyenet.util.domain.normalize_host`
— lowercase ASCII punycode, no trailing dot, no ``*`` literal. CHECKs at
the SQL layer enforce these so a backend that bypasses the helper still
fails closed.

Partial-unique "one primary per source" uses the same generated-column
pattern as :class:`eyenet.models.case.CaseMemberTable.active_case_id`:
the generated column materializes ``source_id`` when the row is BOTH
active (``removed_at IS NULL``) AND primary, NULL otherwise. A plain
``UNIQUE`` on the generated column then enforces partial-unique without
relying on dialect-specific partial-index syntax (which CLAUDE.md §2.3
Rule 1 forbids in model files anyway).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CHAR, CheckConstraint, Column, Computed, Index, UniqueConstraint
from sqlmodel import Field, SQLModel

from eyenet.contracts.enums import SourceDomainPatternKind

from ._base import new_uuid7


class SourceDomainTable(SQLModel, table=True):
    """`source_domain` — hostname → Source binding (MODELS §2.26)."""

    __tablename__ = "source_domain"
    __table_args__ = (
        CheckConstraint("length(pattern) >= 1", name="ck_source_domain_pattern_nonempty"),
        CheckConstraint("pattern = lower(pattern)", name="ck_source_domain_pattern_lower"),
        CheckConstraint("instr(pattern, '*') = 0", name="ck_source_domain_pattern_no_star"),
        # SQLAlchemy's default StrEnum mapping stores .name (uppercase),
        # not .value — same convention as case_v2.status, observation.tier,
        # etc. The CHECK enumerates the *stored* form so a backend that
        # bypasses the ORM (raw INSERT in a test or admin tool) still fails
        # closed.
        CheckConstraint(
            "pattern_kind IN ('EXACT', 'SUBDOMAIN_WILDCARD', 'SUFFIX_MATCH')",
            name="ck_source_domain_pattern_kind",
        ),
        CheckConstraint(
            "notes IS NULL OR length(notes) > 0",
            name="ck_source_domain_notes_nonempty",
        ),
        # Triplet: removed_at and removed_by_user_id must agree (both NULL or both set).
        CheckConstraint(
            "(removed_at IS NULL AND removed_by_user_id IS NULL) "
            "OR (removed_at IS NOT NULL AND removed_by_user_id IS NOT NULL)",
            name="ck_source_domain_remove_pair",
        ),
        # One primary per source — generated-column partial-unique
        # (same trick as CaseMemberTable.active_case_id).
        UniqueConstraint(
            "active_primary_source_id",
            name="uq_source_domain_one_primary",
        ),
        # Hot path: "find Source for host X" — pattern + kind specificity lookup.
        Index("ix_source_domain_pattern_kind", "pattern", "pattern_kind"),
        # "List all domains for source X."
        Index("ix_source_domain_source", "source_id", "removed_at"),
    )

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    source_id: UUID = Field(foreign_key="source.id", index=True)
    pattern: str = Field(max_length=253)
    pattern_kind: SourceDomainPatternKind
    is_primary: bool = Field(default=False)
    created_at: datetime
    created_by_user_id: UUID | None = Field(default=None, foreign_key="system_user.id")
    removed_at: datetime | None = None
    removed_by_user_id: UUID | None = Field(default=None, foreign_key="system_user.id")
    notes: str | None = Field(default=None, max_length=1024)
    # Generated column: equals source_id when this row is BOTH active
    # (removed_at IS NULL) AND primary, NULL otherwise. Drives the
    # partial-unique above. NOT a field a caller ever writes — the
    # database materializes it from is_primary + removed_at.
    active_primary_source_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            "active_primary_source_id",
            CHAR(32),
            Computed(
                "CASE WHEN is_primary AND removed_at IS NULL THEN source_id ELSE NULL END",
                persisted=True,
            ),
            index=True,
        ),
    )


__all__ = ["SourceDomainTable"]
