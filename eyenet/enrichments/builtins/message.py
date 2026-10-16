# SPDX-License-Identifier: AGPL-3.0-or-later
"""Message-source enrichments: author, container, artifacts."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlmodel import col, select

from eyenet.enrichments.base import LocalSQLEnrichment
from eyenet.models import InfrastructureArtifactMentionTable, MessageTable

if TYPE_CHECKING:
    from uuid import UUID

_M = MessageTable
_MN = InfrastructureArtifactMentionTable


class MessageAuthor(LocalSQLEnrichment):
    src_type = "message"
    name = "author"
    output_type = "actor"
    edge_kind = "authored_by"
    single = True

    def build_select(self, src_id: UUID) -> tuple[Any, Any]:
        return select(_M.actor_id).where(_M.id == src_id), col(_M.actor_id)


class MessageContainer(LocalSQLEnrichment):
    src_type = "message"
    name = "container"
    output_type = "group"
    edge_kind = "in"
    single = True

    def build_select(self, src_id: UUID) -> tuple[Any, Any]:
        return select(_M.group_id).where(_M.id == src_id), col(_M.group_id)


class MessageArtifacts(LocalSQLEnrichment):
    src_type = "message"
    name = "artifacts"
    output_type = "artifact"
    edge_kind = "mentions"

    def build_select(self, src_id: UUID) -> tuple[Any, Any]:
        return select(_MN.artifact_id).where(_MN.message_id == src_id), col(_MN.artifact_id)
