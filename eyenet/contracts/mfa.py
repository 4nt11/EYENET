"""MFA row contracts (M9.A3, API_PLAN §M9.A3).

Plain :class:`BaseModel` rows — natural UUID7 PK on ``challenge_id``.

Surface: db (Surface=db per PLAN §4.2 — no bus subject).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class MfaChallengeRow(BaseModel):
    """One TOTP challenge issued during the login flow (API_PLAN §M9.A3)."""

    model_config = ConfigDict(extra="forbid")

    challenge_id: UUID
    user_id: UUID
    issued_at: datetime
    expires_at: datetime
    consumed_at: datetime | None = None
    failed_attempts: int = Field(default=0, ge=0)


__all__ = ["MfaChallengeRow"]
