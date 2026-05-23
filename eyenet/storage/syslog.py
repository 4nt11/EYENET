"""SQLiteSystemLogStore — allowlist-gated writes (PLAN §9.5)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.engine import Engine
from sqlmodel import Session

from eyenet.contracts.enums import SystemLogLevel
from eyenet.contracts.syslog import SYSLOG_ALLOWLIST
from eyenet.models import SystemLogTable


class SQLiteSystemLogStore:
    """Persists curated lifecycle/warn/error events. Off-allowlist events
    are silently dropped for caller convenience — the discipline is on the
    emitter to use the allowlist names; this store is the gate.
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    async def append(
        self,
        *,
        level: SystemLogLevel,
        service: str,
        instance_id: str,
        event: str,
        message: str,
        trace_id: str | None = None,
        span_id: str | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
        stack_hash: str | None = None,
        fields: dict[str, Any] | None = None,
    ) -> bool:
        """Returns True if persisted, False if event was off-allowlist."""

        if (
            level in (SystemLogLevel.LIFECYCLE, SystemLogLevel.NOTICE)
            and event not in SYSLOG_ALLOWLIST
        ):
            return False
        # warn / error always persist regardless of allowlist membership.
        with Session(self._engine) as session:
            row = SystemLogTable(
                level=level,
                service=service,
                instance_id=instance_id,
                event=event,
                message=message,
                trace_id=trace_id,
                span_id=span_id,
                error_type=error_type,
                error_message=error_message,
                stack_hash=stack_hash,
                fields=fields or {},
                at=datetime.now(tz=UTC),
            )
            session.add(row)
            session.commit()
        return True


__all__ = ["SQLiteSystemLogStore"]
