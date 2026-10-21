# SPDX-License-Identifier: AGPL-3.0-or-later
"""Assemble a MessageDetail from one MessageTable row.

Shared by the message and thread by-id routes (a thread's OP is a message).
Mirrors the group-messages reader's per-post assembly, for a single id.
"""

from __future__ import annotations

from typing import cast
from uuid import UUID

from eyenet.api.v1.schemas.groups import GroupMessage
from eyenet.api.v1.schemas.messages import MessageDetail
from eyenet.contracts.incident import IncidentLabelRow, MessageGeoRow
from eyenet.models.infrastructure import InfrastructureArtifactTable
from eyenet.models.message import MessageTable
from eyenet.storage.repository import BaseRepository


async def build_message_detail(storage: BaseRepository, msg: MessageTable) -> MessageDetail:
    """One message -> its full detail: author, source, body, incident labels, artifacts."""
    mid = msg.id
    labels = await storage.incident_labels_for_messages([mid])
    corrections = cast(
        "dict[UUID, IncidentLabelRow]", await storage.incident_labels_by_message_ids([mid])
    )
    geo = cast("dict[UUID, MessageGeoRow]", await storage.message_geo_by_message_ids([mid]))
    actors = await storage.actors_by_ids([msg.actor_id])
    source = await storage.get_source(msg.source_id)
    artifacts = cast("list[InfrastructureArtifactTable]", await storage.artifacts_for_message(mid))
    message = GroupMessage.from_message(
        msg, labels.get(mid), corrections.get(mid), geo.get(mid), actors.get(msg.actor_id)
    )
    return MessageDetail.build(
        msg,
        message,
        source_display=getattr(source, "display_name", None),
        artifacts=artifacts,
    )
