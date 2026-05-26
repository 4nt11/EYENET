"""EYENET SQLModel tables.

Importing this module registers every table on `SQLModel.metadata`. Per
PLAN §5.2, the storage layer (M1+) physically routes them across one SQLite
file per concern using per-store engines bound to the same metadata —
NOT by splitting metadata at this layer.
"""

from __future__ import annotations

from sqlmodel import SQLModel

from .actor import ActorAliasHistoryTable, ActorTable
from .audit import AuditLogTable
from .candidates import GroupCandidateMentionTable, GroupCandidateTable
from .case import CaseCollaboratorTable, CaseMemberTable, CaseTable
from .membership import CollectorGroupMembershipTable, MessageObservationTable
from .clearance import SystemUserClearanceGrantTable
from .collector import CollectorTable
from .corpus import CorpusCursorTable
from .feedback import FeedbackGroundTruth, FeedbackPairTable
from .graph import GraphEdgeTable, GraphEdgeType, GraphNodeTable, GraphNodeType
from .group import GroupSnapshotTable, GroupTable
from .identity import (
    EngagementAuthorizationTable,
    IdentityLabelTable,
    IdentityTable,
)
from .infrastructure import ActorArtifactTable, InfrastructureArtifactTable
from .linkage import LinkageTable
from .message import AttachmentTable, MessageTable
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
    "AuditLogTable",
    "CaseCollaboratorTable",
    "CaseMemberTable",
    "CaseTable",
    "CollectorGroupMembershipTable",
    "CollectorTable",
    "GroupCandidateMentionTable",
    "GroupCandidateTable",
    "MessageObservationTable",
    "CorpusCursorTable",
    "EngagementAuthorizationTable",
    "FeedbackGroundTruth",
    "FeedbackPairTable",
    "GraphEdgeTable",
    "GraphEdgeType",
    "GraphNodeTable",
    "GraphNodeType",
    "GroupSnapshotTable",
    "GroupTable",
    "IdentityLabelTable",
    "IdentityTable",
    "InfrastructureArtifactTable",
    "LinkageTable",
    "MembershipTable",
    "MessageTable",
    "ObservationTable",
    "PersonaMembershipTable",
    "PersonaTable",
    "ProfileTable",
    "ReactionTable",
    "SQLModel",
    "SourceDomainTable",
    "SourceTable",
    "SystemLogTable",
    "SystemUserClearanceGrantTable",
    "SystemUserTable",
]
