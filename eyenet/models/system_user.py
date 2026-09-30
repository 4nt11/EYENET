"""SystemUserTable — see contracts/system_user.py."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy.sql.elements import quoted_name
from sqlmodel import Field, SQLModel

from eyenet.contracts.enums import SystemUserRole

from ._base import new_uuid7


class SystemUserTable(SQLModel, table=True):
    # ``system_user`` became a RESERVED keyword in SQL:2016 / Postgres 16
    # (SYSTEM_USER). SQLAlchemy does not know it is reserved, so force-quote the
    # identifier: harmless on SQLite (same table), required on Postgres.
    # quoted_name is a str subclass, so metadata.tables["system_user"] and the
    # _MAIN_TABLES frozenset still resolve unchanged.
    __tablename__ = quoted_name("system_user", quote=True)

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
