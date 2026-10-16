# SPDX-License-Identifier: AGPL-3.0-or-later
"""Artifact-source enrichments: messages, actors."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlmodel import col, select

from eyenet.enrichments.base import LocalSQLEnrichment
from eyenet.models import InfrastructureArtifactMentionTable, MessageTable

if TYPE_CHECKING:
    from uuid import UUID

_M = MessageTable
_MN = InfrastructureArtifactMentionTable


class ArtifactMessages(LocalSQLEnrichment):
    src_type = "artifact"
    name = "messages"
    output_type = "message"
    edge_kind = "mentioned_in"

    def build_select(self, src_id: UUID) -> tuple[Any, Any]:
        return select(_MN.message_id).where(_MN.artifact_id == src_id), col(_MN.message_id)


class ArtifactActors(LocalSQLEnrichment):
    src_type = "artifact"
    name = "actors"
    output_type = "actor"
    edge_kind = "mentioned_by"

    def build_select(self, src_id: UUID) -> tuple[Any, Any]:
        return (
            select(_M.actor_id)
            .join(_MN, col(_MN.message_id) == col(_M.id))
            .where(_MN.artifact_id == src_id)
            .distinct()
        ), col(_M.actor_id)
