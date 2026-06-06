"""CollectorSupervisor command shapes (API_PLAN §4.12.4).

Typed commands the supervisor emits onto a collector's command channel. In
M9.E3 the supervisor records the command in the ``candidate.joining`` audit
payload as the record of intent and writes ``approved → joining``; in M9.E5 it
*also* publishes the command (via :func:`command_subject_for`) and the collector
process running the leased scout identity executes the platform join. The
``access_artifact_id`` selection (MODELS §2.24) also lands with E5 — it is
optional here.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class JoinGroupCommand(BaseModel):
    """Tell a collector to join a candidate group using a leased scout."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["join_group"] = "join_group"
    candidate_id: UUID
    platform_groupid: str
    scout_identity_id: UUID
    # E5 supervisor selects the access artifact before dispatch (MODELS §2.24).
    access_artifact_id: UUID | None = None


class LeaveGroupCommand(BaseModel):
    """Tell a collector to leave a group (operator park / supervisor-detected ban)."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["leave_group"] = "leave_group"
    group_id: UUID
    reason: str


def command_subject_for(scout_instance_id: str) -> str:
    """Bus subject for a collector's command channel (M9.E5, §4.12.4).

    Keyed by the *scout's* ``instance_id`` (``compute_instance_id(scout_name,
    source_kind)``) so the command reaches the collector process running that
    leased scout identity. Lives under the ``eyenet.control.`` prefix the
    panic/kill-switch channel already uses.
    """
    return f"eyenet.control.collector.{scout_instance_id}.command"


__all__ = ["JoinGroupCommand", "LeaveGroupCommand", "command_subject_for"]
