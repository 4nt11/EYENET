# SPDX-License-Identifier: AGPL-3.0-or-later
"""Actor-source enrichments: messages, artifacts, groups, linked, related."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import case, or_
from sqlmodel import col, select

from eyenet.enrichments.base import LocalSQLEnrichment
from eyenet.models import (
    ActorRelationTable,
    InfrastructureArtifactMentionTable,
    LinkageTable,
    MessageTable,
)

if TYPE_CHECKING:
    from uuid import UUID

_M = MessageTable
_MN = InfrastructureArtifactMentionTable


class ActorMessages(LocalSQLEnrichment):
    src_type = "actor"
    name = "messages"
    output_type = "message"
    edge_kind = "authored"

    def build_select(self, src_id: UUID) -> tuple[Any, Any]:
        return select(_M.id).where(_M.actor_id == src_id), col(_M.id)


class ActorArtifacts(LocalSQLEnrichment):
    src_type = "actor"
    name = "artifacts"
    output_type = "artifact"
    edge_kind = "uses_infra"

    def build_select(self, src_id: UUID) -> tuple[Any, Any]:
        return (
            select(_MN.artifact_id)
            .join(_M, col(_MN.message_id) == col(_M.id))
            .where(_M.actor_id == src_id)
            .distinct()
        ), col(_MN.artifact_id)


class ActorGroups(LocalSQLEnrichment):
    src_type = "actor"
    name = "groups"
    output_type = "group"
    edge_kind = "active_in"

    def build_select(self, src_id: UUID) -> tuple[Any, Any]:
        return select(_M.group_id).where(_M.actor_id == src_id).distinct(), col(_M.group_id)


class ActorLinked(LocalSQLEnrichment):
    src_type = "actor"
    name = "linked"
    output_type = "actor"
    edge_kind = "linked"

    def build_select(self, src_id: UUID) -> tuple[Any, Any]:
        other = case(
            (col(LinkageTable.actor_a_id) == src_id, col(LinkageTable.actor_b_id)),
            else_=col(LinkageTable.actor_a_id),
        )
        where = or_(col(LinkageTable.actor_a_id) == src_id, col(LinkageTable.actor_b_id) == src_id)
        return select(other).where(where).distinct(), other


class ActorRelated(LocalSQLEnrichment):
    src_type = "actor"
    name = "related"
    output_type = "actor"
    edge_kind = "related"

    def build_select(self, src_id: UUID) -> tuple[Any, Any]:
        other = case(
            (col(ActorRelationTable.from_actor_id) == src_id, col(ActorRelationTable.to_actor_id)),
            else_=col(ActorRelationTable.from_actor_id),
        )
        where = or_(
            col(ActorRelationTable.from_actor_id) == src_id,
            col(ActorRelationTable.to_actor_id) == src_id,
        )
        return select(other).where(where).distinct(), other
