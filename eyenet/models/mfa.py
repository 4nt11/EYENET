"""MFA tables (M9.A3, API_PLAN §M9.A3).

One table backing the TOTP login-challenge flow:

* :class:`MfaChallengeTable` — one-shot per login attempt. ``challenge_id`` is
  echoed back by the client to ``POST /v1/auth/login/verify`` to complete the
  second factor. ``consumed_at`` marks the row spent (success); ``failed_attempts``
  counts wrong codes against the same challenge. The 5-fail / 15-min lockout
  query is a window scan over rows for the user with ``failed_attempts > 0``.

CHECK: ``consumed_at IS NULL OR consumed_at >= issued_at`` (a consumed row
must have been consumed AFTER it was issued). The (user_id, issued_at)
composite index supports the lockout window scan without a sequential scan.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, Index
from sqlmodel import Field, SQLModel

from ._base import new_uuid7


class MfaChallengeTable(SQLModel, table=True):
    """`mfa_challenge` — one-shot TOTP challenge issued by /v1/auth/login (M9.A3)."""

    __tablename__ = "mfa_challenge"
    __table_args__ = (
        CheckConstraint(
            "consumed_at IS NULL OR consumed_at >= issued_at",
            name="ck_mfa_challenge_consumed_after_issued",
        ),
        Index("ix_mfa_challenge_user_issued", "user_id", "issued_at"),
    )

    challenge_id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    user_id: UUID = Field(foreign_key="system_user.id", index=True)
    issued_at: datetime
    expires_at: datetime
    consumed_at: datetime | None = None
    failed_attempts: int = Field(default=0, ge=0)


__all__ = ["MfaChallengeTable"]
