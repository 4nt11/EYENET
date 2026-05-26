"""v1 HTTP API schema namespace.

This package is the Python side of `contracts/openapi/eyenet.v1.yaml`.
Every wire-shape model the v1 surface emits or accepts lives here, one
file per resource group. The OpenAPI document is the contract; these
Pydantic classes are its Python projection.

API_PLAN §9.1.
"""

from __future__ import annotations

from .actors import (
    ActorDetail,
    ActorSummary,
    BelongsToPersonaAttrs,
    BelongsToPersonaEdge,
    CursorPageActorSummary,
    CursorPageObservationSummary,
    CursorPageTimelineEntry,
    LinkedToAttrs,
    LinkedToEdge,
    NeighborEdge,
    NeighborList,
    ObservationSummary,
    TimelineEntry,
)
from .anchors import Anchor, CursorPageAnchor
from .attachments import (
    FileAccessAcknowledgment,
    FileAccessExoneration,
    FileAccessJournalEntry,
    FileManifest,
)
from .audit import AuditChainBreak, AuditRow, AuditVerifyResult, CursorPageAuditRow
from .auth import (
    CursorPagePATSummary,
    LoginRequest,
    LogoutRequest,
    PATMinted,
    PATMintRequest,
    PATSummary,
    RefreshRequest,
    StreamTokenMinted,
    StreamTokenRequest,
    TokenPair,
    UserMe,
)
from .cases import (
    CaseArchiveRequest,
    CaseCloseRequest,
    CaseCollaboratorAddRequest,
    CaseCollaboratorRevokeRequest,
    CaseCollaboratorSummary,
    CaseCreateRequest,
    CaseDetail,
    CaseMemberAddRequest,
    CaseMemberBulkAddRequest,
    CaseMemberBulkRemoveRequest,
    CaseMemberBulkResult,
    CaseMemberRemoveRequest,
    CaseMemberSubjectRef,
    CaseMemberSummary,
    CaseReopenRequest,
    CaseSummary,
    CaseUpdateRequest,
    CursorPageCaseCollaboratorSummary,
    CursorPageCaseMemberSummary,
    CursorPageCaseSummary,
)
from .clearance import (
    ClearanceGrantDetail,
    ClearanceGrantRequest,
    ClearanceGrantSummary,
    ClearanceRevokeRequest,
    CursorPageClearanceGrantSummary,
)
from .enums import (
    CaseRoleOnCase,
    CaseStatus,
    CaseSubjectKind,
    ClearanceScope,
    FileServedVia,
    LinkageState,
    ReclassificationSubjectKind,
    SensitivityTier,
    StreamTopic,
    SystemUserRole,
)
from .errors import ProblemDetail, ValidationError
from .graph import GraphStats, LinkageStateCounts
from .health import HealthStatus, ReadyComponents, ReadyStatus
from .identities import IdentityActionRequest, PanicRequest
from .linkages import (
    CursorPageLinkageSummary,
    LinkageDecisionRequest,
    LinkageDetail,
    LinkageEvidence,
    LinkageSummary,
)
from .pagination import CursorPage
from .personas import CursorPagePersonaMember, PersonaDetail, PersonaMember, PersonaSummary
from .reclassify import ReclassificationRequest, ReclassificationResult
from .redaction import RedactionMarker
from .stream import (
    AuditEvent,
    ControlEvent,
    LinkageProposedEvent,
    LinkageStateChangedEvent,
    PersonaUpdatedEvent,
    StreamGapEvent,
)
from .writes import WriteAccepted

__all__ = [
    "ActorDetail",
    "ActorSummary",
    "Anchor",
    "AuditChainBreak",
    "AuditEvent",
    "AuditRow",
    "AuditVerifyResult",
    "BelongsToPersonaAttrs",
    "BelongsToPersonaEdge",
    "CaseArchiveRequest",
    "CaseCloseRequest",
    "CaseCollaboratorAddRequest",
    "CaseCollaboratorRevokeRequest",
    "CaseCollaboratorSummary",
    "CaseCreateRequest",
    "CaseDetail",
    "CaseMemberAddRequest",
    "CaseMemberBulkAddRequest",
    "CaseMemberBulkRemoveRequest",
    "CaseMemberBulkResult",
    "CaseMemberRemoveRequest",
    "CaseMemberSubjectRef",
    "CaseMemberSummary",
    "CaseReopenRequest",
    "CaseRoleOnCase",
    "CaseStatus",
    "CaseSubjectKind",
    "CaseSummary",
    "CaseUpdateRequest",
    "ClearanceGrantDetail",
    "ClearanceGrantRequest",
    "ClearanceGrantSummary",
    "ClearanceRevokeRequest",
    "ClearanceScope",
    "ControlEvent",
    "CursorPage",
    "CursorPageActorSummary",
    "CursorPageAnchor",
    "CursorPageAuditRow",
    "CursorPageCaseCollaboratorSummary",
    "CursorPageCaseMemberSummary",
    "CursorPageCaseSummary",
    "CursorPageClearanceGrantSummary",
    "CursorPageLinkageSummary",
    "CursorPageObservationSummary",
    "CursorPagePATSummary",
    "CursorPagePersonaMember",
    "CursorPageTimelineEntry",
    "FileAccessAcknowledgment",
    "FileAccessExoneration",
    "FileAccessJournalEntry",
    "FileManifest",
    "FileServedVia",
    "GraphStats",
    "HealthStatus",
    "IdentityActionRequest",
    "LinkageDecisionRequest",
    "LinkageDetail",
    "LinkageEvidence",
    "LinkageProposedEvent",
    "LinkageState",
    "LinkageStateChangedEvent",
    "LinkageStateCounts",
    "LinkageSummary",
    "LinkedToAttrs",
    "LinkedToEdge",
    "LoginRequest",
    "LogoutRequest",
    "NeighborEdge",
    "NeighborList",
    "ObservationSummary",
    "PATMintRequest",
    "PATMinted",
    "PATSummary",
    "PanicRequest",
    "PersonaDetail",
    "PersonaMember",
    "PersonaSummary",
    "PersonaUpdatedEvent",
    "ProblemDetail",
    "ReadyComponents",
    "ReadyStatus",
    "ReclassificationRequest",
    "ReclassificationResult",
    "ReclassificationSubjectKind",
    "RedactionMarker",
    "RefreshRequest",
    "SensitivityTier",
    "StreamGapEvent",
    "StreamTokenMinted",
    "StreamTokenRequest",
    "StreamTopic",
    "SystemUserRole",
    "TimelineEntry",
    "TokenPair",
    "UserMe",
    "ValidationError",
    "WriteAccepted",
]
