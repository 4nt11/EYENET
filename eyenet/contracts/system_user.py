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

from pydantic import Field

from ._base import DbRowBase
from .enums import SystemUserRole


class SystemUserRow(DbRowBase):
    """Persisted operator account."""

    username: str
    display_name: str
    email: str | None = None
    password_hash: str = Field(description="argon2id; never plaintext")
    role: SystemUserRole = SystemUserRole.VIEWER
    is_active: bool = True
    last_login_at: datetime | None = None
    created_at: datetime
    mfa_secret_encrypted: str | None = Field(default=None, description="age-encrypted TOTP")
    notes: str | None = None


__all__ = ["SystemUserRow"]
