"""EYENET SQLModel tables.

Importing this module registers every table on `SQLModel.metadata`. Per
PLAN §5.2, the storage layer (M1+) physically routes them across one SQLite
file per concern using per-store engines bound to the same metadata —
NOT by splitting metadata at this layer.
"""

from __future__ import annotations

from sqlmodel import SQLModel

from .access_artifact import GroupAccessArtifactTable
from .actor import ActorAliasHistoryTable, ActorTable
from .anchor import AuditAnchorTable
from .audit import AuditLogTable
from .auth import (
    JwtDenylistTable,
    PersonalAccessTokenTable,
    RefreshTokenTable,
    SystemUserCredentialTable,
    SystemUserScopeTable,
)
from .candidates import GroupCandidateMentionTable, GroupCandidateTable
from .case import CaseCollaboratorTable, CaseMemberTable, CaseTable
from .clearance import SystemUserClearanceGrantTable
from .collector import CollectorTable
from .corpus import CorpusCursorTable
from .document import DocumentTable
from .event_logs import (
    IdentityEventLogTable,
    LinkageEventLogTable,
    PersonaEventLogTable,
)
from .feedback import FeedbackGroundTruth, FeedbackPairTable
from .file_access import (
    FileAccessAcknowledgmentTable,
    FileAccessJournalTable,
    SigningKeyChallengeTable,
    SystemUserSigningPubkeyHistoryTable,
)
from .graph import GraphEdgeTable, GraphEdgeType, GraphNodeTable, GraphNodeType
from .group import GroupSnapshotTable, GroupTable
from .idempotency import IdempotencyRecordTable
from .identity import (
    EngagementAuthorizationTable,
    IdentityLabelTable,
    IdentityTable,
)
from .infrastructure import ActorArtifactTable, InfrastructureArtifactTable
from .linkage import LinkageTable
from .linkage_verifier_result import LinkageVerifierResultTable
from .membership import CollectorGroupMembershipTable, MessageObservationTable
from .message import AttachmentTable, MessageTable
from .mfa import MfaChallengeTable
from .observation import ObservationTable
from .persona import PersonaMembershipTable, PersonaTable
from .profile import ProfileTable
from .reaction import ReactionTable
from .social_graph import MembershipTable
from .source import SourceTable
from .source_domain import SourceDomainTable
from .syslog import SystemLogTable
from .system_user import SystemUserTable

__all__ = [
    "ActorAliasHistoryTable",
    "ActorArtifactTable",
    "ActorTable",
    "AttachmentTable",
    "AuditAnchorTable",
    "AuditLogTable",
    "CaseCollaboratorTable",
    "CaseMemberTable",
    "CaseTable",
    "CollectorGroupMembershipTable",
    "CollectorTable",
    "CorpusCursorTable",
    "DocumentTable",
    "EngagementAuthorizationTable",
    "FeedbackGroundTruth",
    "FeedbackPairTable",
    "FileAccessAcknowledgmentTable",
    "FileAccessJournalTable",
    "GraphEdgeTable",
    "GraphEdgeType",
    "GraphNodeTable",
    "GraphNodeType",
    "GroupAccessArtifactTable",
    "GroupCandidateMentionTable",
    "GroupCandidateTable",
    "GroupSnapshotTable",
    "GroupTable",
    "IdempotencyRecordTable",
    "IdentityEventLogTable",
    "IdentityLabelTable",
    "IdentityTable",
    "InfrastructureArtifactTable",
    "JwtDenylistTable",
    "LinkageEventLogTable",
    "LinkageTable",
    "LinkageVerifierResultTable",
    "MembershipTable",
    "MessageObservationTable",
    "MessageTable",
    "MfaChallengeTable",
    "ObservationTable",
    "PersonaEventLogTable",
    "PersonaMembershipTable",
    "PersonaTable",
    "PersonalAccessTokenTable",
    "ProfileTable",
    "ReactionTable",
    "RefreshTokenTable",
    "SQLModel",
    "SigningKeyChallengeTable",
    "SourceDomainTable",
    "SourceTable",
    "SystemLogTable",
    "SystemUserClearanceGrantTable",
    "SystemUserCredentialTable",
    "SystemUserScopeTable",
    "SystemUserSigningPubkeyHistoryTable",
    "SystemUserTable",
]
