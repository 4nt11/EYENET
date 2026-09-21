"""Operator control-plane bus contracts (API_PLAN §3.4).

The global panic freeze. Published on the ``eyenet.control.`` channel every
service already watches for system-wide operator actions (kill-switch, freeze).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from ._base import BusEnvelope

SUBJECT_PANIC: str = "eyenet.control.panic"


class PanicEnvelope(BusEnvelope):
    """`eyenet.control.panic` — global operator freeze. Every service reacts
    (collectors stop, modes lock); the UI raises a banner off the control
    stream. The payload is intentionally minimal — full forensic detail lives
    in the audit chain."""

    declared_by: str = Field(description="system_user id")
    declared_at: datetime
    reason: str


__all__ = ["SUBJECT_PANIC", "PanicEnvelope"]
