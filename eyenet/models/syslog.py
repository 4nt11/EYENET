"""SystemLogTable — see contracts/syslog.py.

Indexes per MODELS §2.18: (service, level, at DESC) for the operator log
view; (stack_hash, at DESC) for "show me all instances of this error."
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, Index
from sqlmodel import Column, Field, SQLModel

from eyenet.contracts.enums import SystemLogLevel

from ._base import new_uuid7


class SystemLogTable(SQLModel, table=True):
    __tablename__ = "system_log"
    __table_args__ = (
        Index("ix_systemlog_service_level_at", "service", "level", "at"),
        Index("ix_systemlog_stack_at", "stack_hash", "at"),
    )

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    level: SystemLogLevel
    service: str
    instance_id: str
    event: str
    message: str
    trace_id: str | None = None
    span_id: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    stack_hash: str | None = None
    fields: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    at: datetime


__all__ = ["SystemLogTable"]
