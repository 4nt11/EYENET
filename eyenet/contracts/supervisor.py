"""CollectorSupervisor command shapes (API_PLAN §4.12.4).

Typed commands the supervisor emits onto a collector's command channel. In
M9.E3 the supervisor records the command in the ``candidate.joining`` audit
payload as the record of intent and writes ``approved → joining``; the actual
platform dispatch + ``joining → joined`` is the collector's job in E5. The
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


__all__ = ["JoinGroupCommand", "LeaveGroupCommand"]
