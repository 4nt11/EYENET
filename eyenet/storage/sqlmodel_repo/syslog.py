# SPDX-License-Identifier: AGPL-3.0-or-later
"""SyslogMixin — allowlist-gated system log append (PLAN §9.5)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from eyenet.contracts.enums import SystemLogLevel
from eyenet.contracts.syslog import SYSLOG_ALLOWLIST
from eyenet.models import SystemLogTable

from ._helpers import safe_session


class SyslogMixin:
    async def append_syslog(
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
        if (
            level in (SystemLogLevel.LIFECYCLE, SystemLogLevel.NOTICE)
            and event not in SYSLOG_ALLOWLIST
        ):
            return False
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
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
            await session.commit()
        return True


__all__ = ["SyslogMixin"]
