"""SystemUserTable — see contracts/system_user.py."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlmodel import Field, SQLModel

from eyenet.contracts.enums import SystemUserRole

from ._base import new_uuid7


class SystemUserTable(SQLModel, table=True):
    __tablename__ = "system_user"

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    username: str = Field(unique=True, index=True)
    display_name: str
    email: str | None = Field(default=None, index=True)
    role: SystemUserRole = Field(default=SystemUserRole.VIEWER, index=True)
    is_active: bool = True
    last_login_at: datetime | None = None
    created_at: datetime
    notes: str | None = None
    # Secret material (password_hash, mfa_secret_encrypted) lives in
    # `system_user_credential` (M9.A1). One-to-one with this row.


__all__ = ["SystemUserTable"]
