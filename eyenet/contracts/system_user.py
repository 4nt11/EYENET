"""`SystemUser` — operator(s) of EYENET itself (MODELS §2.17, PLAN §12).

Multi-user is in scope as of 2026-05-04. v0 default is single-user, but the
model supports N from the start ("design plural from day one").

Permissions sketch (MODELS §2.17):
  admin   — everything, incl. SystemUser CRUD, identity pool, kill switch.
  analyst — read all, write labels/cases/linkage decisions, dereference evidence.
  viewer  — read-only, evidence dereference still audited.

Surface: db.
"""

from __future__ import annotations

from datetime import datetime

from ._base import DbRowBase
from .enums import SystemUserRole


class SystemUserRow(DbRowBase):
    """Persisted operator account.

    Secret material (password_hash, MFA secret) lives in the separate
    :class:`SystemUserCredentialRow` table per M9.A1 — profile and credentials
    have different access patterns and audit scopes.
    """

    username: str
    display_name: str
    email: str | None = None
    role: SystemUserRole = SystemUserRole.VIEWER
    is_active: bool = True
    last_login_at: datetime | None = None
    created_at: datetime
    notes: str | None = None


__all__ = ["SystemUserRow"]
