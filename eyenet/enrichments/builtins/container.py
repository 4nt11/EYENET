# SPDX-License-Identifier: AGPL-3.0-or-later
"""Thread- and group-source enrichments (both are message containers keyed by
``group_id``): thread.{messages,participants,op} + group.{messages,participants}."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlmodel import col, select

from eyenet.enrichments.base import LocalSQLEnrichment
from eyenet.models import MessageTable

if TYPE_CHECKING:
    from uuid import UUID

_M = MessageTable


class ThreadMessages(LocalSQLEnrichment):
    src_type = "thread"
    name = "messages"
    output_type = "message"
    edge_kind = "in_thread"

    def build_select(self, src_id: UUID) -> tuple[Any, Any]:
        return select(_M.id).where(_M.group_id == src_id), col(_M.id)


class ThreadParticipants(LocalSQLEnrichment):
    src_type = "thread"
    name = "participants"
    output_type = "actor"
    edge_kind = "posted_in"

    def build_select(self, src_id: UUID) -> tuple[Any, Any]:
        return select(_M.actor_id).where(_M.group_id == src_id).distinct(), col(_M.actor_id)


class ThreadOp(LocalSQLEnrichment):
    src_type = "thread"
    name = "op"
    output_type = "actor"
    edge_kind = "started"
    single = True

    def build_select(self, src_id: UUID) -> tuple[Any, Any]:
        return (
            select(_M.actor_id)
            .where(_M.group_id == src_id)
            .order_by(col(_M.sent_at_source).asc(), col(_M.id).asc())
            .limit(1)
        ), col(_M.actor_id)


class GroupMessages(LocalSQLEnrichment):
    src_type = "group"
    name = "messages"
    output_type = "message"
    edge_kind = "in_group"

    def build_select(self, src_id: UUID) -> tuple[Any, Any]:
        return select(_M.id).where(_M.group_id == src_id), col(_M.id)


class GroupParticipants(LocalSQLEnrichment):
    src_type = "group"
    name = "participants"
    output_type = "actor"
    edge_kind = "active_in"

    def build_select(self, src_id: UUID) -> tuple[Any, Any]:
        return select(_M.actor_id).where(_M.group_id == src_id).distinct(), col(_M.actor_id)
