"""API-facing enums.

Domain enums from `eyenet.contracts.enums` are re-exported (not redefined)
so the wire and storage stay enum-equal. `StreamTopic` is API-only — it
names the four bus-subject families exposed by `/v1/stream/all?topic=...`.
"""

from __future__ import annotations

from enum import StrEnum

from eyenet.contracts.enums import (
    CaseRoleOnCase,
    CaseStatus,
    CaseSubjectKind,
    ClearanceScope,
    FileServedVia,
    LinkageState,
    ReclassificationSubjectKind,
    SensitivityTier,
    SystemUserRole,
)


class StreamTopic(StrEnum):
    """Topic selector for `/v1/stream/all`.

    Values are bus-subject prefixes; the SSE handler subscribes to
    `<topic>.*` after intersecting with the caller's `stream:*` scopes
    (API_PLAN §3.5).
    """

    ATTRIBUTION_LINKAGE = "attribution.linkage"
    ATTRIBUTION_PERSONA = "attribution.persona"
    EYENET_AUDIT = "eyenet.audit"
    EYENET_CONTROL = "eyenet.control"


__all__ = [
    "CaseRoleOnCase",
    "CaseStatus",
    "CaseSubjectKind",
    "ClearanceScope",
    "FileServedVia",
    "LinkageState",
    "ReclassificationSubjectKind",
    "SensitivityTier",
    "StreamTopic",
    "SystemUserRole",
]
