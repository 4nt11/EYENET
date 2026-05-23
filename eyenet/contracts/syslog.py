"""`SystemLog` — curated operational log persisted in SQLite (MODELS §2.18).

NOT a firehose — debug/info chatter goes to journald only (PLAN §9.4).
What lands here:
  - all `warn` and `error` lines
  - lifecycle events on the curated allowlist
  - notice-level events deemed operator-visible

Surface: db (no bus subject — SystemLog is an in-app SQLite query target).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from ._base import DbRowBase
from .enums import SystemLogLevel

# Curated allowlist of dotted, lowercase event names that route to SystemLog.
# Off-allowlist events go to journald only. Order doesn't matter; uniqueness
# does.
SYSLOG_ALLOWLIST: frozenset[str] = frozenset(
    {
        # Service lifecycle
        "service.start",
        "service.stop",
        "service.ready",
        "service.shutdown",
        # Bus / transport
        "bus.connect",
        "bus.disconnect",
        "bus.reconnect",
        "bus.subject.subscribed",
        # Identity pool
        "identity_pool.state_changed",
        "identity_pool.rotated",
        "identity_pool.frozen",
        # Collector
        "collector.cooldown_hit",
        "collector.rate_limited",
        "collector.degraded",
        # Contract handling
        "contract.version_mismatch_handled",
        # Operator-tier
        "kill_switch.triggered",
        # Linker / linkage decisions
        "linkage.proposed",
        "linkage.suspected",
        "linkage.confirmed",
        "linkage.rejected",
        # Persona aggregation
        "persona.merged",
        "persona.split",
        # Query API lifecycle
        "query_api.started",
        "query_api.stopped",
    }
)


class SystemLogRow(DbRowBase):
    """Persisted operator-visible log entry (MODELS §2.18)."""

    level: SystemLogLevel
    service: str
    instance_id: str
    event: str = Field(description="dotted, lowercase; from SYSLOG_ALLOWLIST")
    message: str
    trace_id: str | None = None
    span_id: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    stack_hash: str | None = Field(default=None, description="sha256 of normalized stack")
    fields: dict[str, Any] = Field(default_factory=dict)
    at: datetime


__all__ = ["SYSLOG_ALLOWLIST", "SystemLogRow"]
