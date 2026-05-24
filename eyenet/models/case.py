"""Case tables — see contracts/case.py (API_PLAN §4.10).

Three tables: `case_v2` (the investigation), `case_member` (m:n evidence
junction), `case_collaborator` (m:n user authorisation). All three live in
`audit.db` per §4.10 — cases are forensic primitives; every membership and
collaborator change emits an `eyenet.audit.case.*` row in the same
transaction.

The `_v2` suffix on `case_v2.__tablename__` is intentional: it makes the
break from the pre-§4.10 stub table (`case_`) explicit. Pre-public, no
migration — the legacy table is dropped by `rm data/*.db && eyenet init`.

Cache-bypass note (§4.4.1): `case_member` and `case_collaborator` resolution
joins the no-cache list. The auth resolver that consumes this lands in
M9.1b; this module just publishes the storage shape.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CHAR, CheckConstraint, Column, Computed, Index, UniqueConstraint
from sqlmodel import Field, SQLModel

from eyenet.contracts.enums import (
    CaseRoleOnCase,
    CaseStatus,
    CaseSubjectKind,
    SensitivityTier,
)

from ._base import new_uuid7


# Triplet-nullability CHECK pattern: three columns must be all-NULL or all-NOT-NULL.
# SQLite-portable; reused for close_*/archive_*/remove_*/revoke_* triplets.
def _triplet_check(name: str, a: str, b: str, c: str) -> CheckConstraint:
    return CheckConstraint(
        f"(({a} IS NULL AND {b} IS NULL AND {c} IS NULL) OR "
        f"({a} IS NOT NULL AND {b} IS NOT NULL AND {c} IS NOT NULL))",
        name=name,
    )


class CaseTable(SQLModel, table=True):
    """`case_v2` — the investigation row (API_PLAN §4.10.1)."""

    __tablename__ = "case_v2"
    __table_args__ = (
        _triplet_check(
            "ck_case_v2_close_triplet",
            "closed_at",
            "closed_by_user_id",
            "close_reason",
        ),
        _triplet_check(
            "ck_case_v2_archive_triplet",
            "archived_at",
            "archived_by_user_id",
            "archive_reason",
        ),
        CheckConstraint("length(title) >= 3", name="ck_case_v2_title_min"),
        Index("ix_case_v2_status_created", "status", "created_at"),
        Index("ix_case_v2_effective_tier", "effective_tier"),
    )

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    title: str = Field(max_length=256)
    description: str | None = Field(default=None, max_length=8192)
    status: CaseStatus = Field(default=CaseStatus.OPEN, index=True)
    effective_tier: SensitivityTier = Field(default=SensitivityTier.NORMAL)
    created_by_user_id: UUID = Field(index=True)
    created_at: datetime
    closed_at: datetime | None = None
    closed_by_user_id: UUID | None = None
    close_reason: str | None = Field(default=None, max_length=1024)
    archived_at: datetime | None = None
    archived_by_user_id: UUID | None = None
    archive_reason: str | None = Field(default=None, max_length=1024)
    # Successor pointer when an archived case is reopened (§4.10.3).
    # No FK because the predecessor may have been deleted in test fixtures;
    # production cases never delete, but the storage layer doesn't enforce.
    parent_case_id: UUID | None = Field(default=None, index=True)


class CaseMemberTable(SQLModel, table=True):
    """`case_member` — m:n evidence junction (API_PLAN §4.10.1).

    `subject_id` may reference rows across all 8 stores (observation lives in
    `observations.db`, attachment in `messages.db`, etc.); no SQL FK is
    declarable. Referential integrity is the storage layer's responsibility
    on the write path.

    Partial unique on `(case_id, subject_kind, subject_id) WHERE removed_at
    IS NULL` prevents double-adding an active row without forbidding a
    soft-deleted + re-added history.
    """

    __tablename__ = "case_member"
    __table_args__ = (
        _triplet_check(
            "ck_case_member_remove_triplet",
            "removed_at",
            "removed_by_user_id",
            "removal_reason",
        ),
        CheckConstraint("length(add_reason) >= 16", name="ck_case_member_reason_min"),
        # Cross-dialect partial-unique: a generated column carries `case_id`
        # for active rows and NULL for removed rows. A plain UNIQUE on
        # `(active_case_id, subject_kind, subject_id)` enforces uniqueness
        # only among rows where the generated column is non-NULL — standard
        # SQL allows multiple NULLs in a UNIQUE constraint. Works on SQLite
        # 3.31+, Postgres, MySQL 5.7+ (all support GENERATED ALWAYS AS).
        UniqueConstraint(
            "active_case_id",
            "subject_kind",
            "subject_id",
            name="uq_case_member_active",
        ),
        # Cache-bypass critical path (§4.4.1): "which cases include this row?"
        Index("ix_case_member_reverse", "subject_kind", "subject_id", "removed_at"),
    )

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    case_id: UUID = Field(foreign_key="case_v2.id", index=True)
    subject_kind: CaseSubjectKind
    subject_id: UUID
    added_by_user_id: UUID = Field(index=True)
    added_at: datetime
    add_reason: str = Field(max_length=1024)
    removed_at: datetime | None = None
    removed_by_user_id: UUID | None = None
    removal_reason: str | None = Field(default=None, max_length=1024)
    # Generated column: equals case_id when the row is active (removed_at IS
    # NULL), NULL otherwise. Drives the partial-unique above. NOT a field a
    # caller ever writes — the database materialises it from `removed_at`.
    active_case_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            "active_case_id",
            CHAR(32),
            Computed("CASE WHEN removed_at IS NULL THEN case_id ELSE NULL END", persisted=True),
            index=True,
        ),
    )


class CaseCollaboratorTable(SQLModel, table=True):
    """`case_collaborator` — m:n user-to-case authorisation (§4.10.1).

    Soft-revoke via `revoked_at`. Partial unique on `(case_id, user_id) WHERE
    revoked_at IS NULL` prevents an active collaborator being granted twice.
    """

    __tablename__ = "case_collaborator"
    __table_args__ = (
        _triplet_check(
            "ck_case_collab_revoke_triplet",
            "revoked_at",
            "revoked_by_user_id",
            "revocation_reason",
        ),
        # Same generated-column trick as case_member (see commentary there).
        UniqueConstraint(
            "active_case_id",
            "user_id",
            name="uq_case_collab_active",
        ),
        # Cache-bypass critical path (§4.4.1): "what cases is user X on?"
        Index("ix_case_collab_user", "user_id", "revoked_at"),
    )

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    case_id: UUID = Field(foreign_key="case_v2.id")
    user_id: UUID
    role_on_case: CaseRoleOnCase
    granted_by_user_id: UUID = Field(index=True)
    granted_at: datetime
    revoked_at: datetime | None = None
    revoked_by_user_id: UUID | None = None
    revocation_reason: str | None = Field(default=None, max_length=1024)
    active_case_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            "active_case_id",
            CHAR(32),
            Computed("CASE WHEN revoked_at IS NULL THEN case_id ELSE NULL END", persisted=True),
            index=True,
        ),
    )


__all__ = ["CaseCollaboratorTable", "CaseMemberTable", "CaseTable"]
