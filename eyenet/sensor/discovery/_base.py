# SPDX-License-Identifier: AGPL-3.0-or-later
"""DiscoveryExtractor seam — base class + the resolved per-message context.

:class:`MessageContext` is the *resolved* shape: the ``DiscoverySensor`` (E2)
turns a :class:`~eyenet.contracts.raw_message.RawMessageEnvelope` (which carries
opaque strings — ``instance_id``, ``platform_groupid``, ``actor_key``) into
this struct of UUIDs + lineage before invoking the registry. E1's
``url_extraction`` only reads ``text`` + ``collected_at``; E2's
``channel_reference_extraction`` uses the full context to write a mention.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from eyenet.storage.repository import BaseRepository


@dataclass(frozen=True)
class MessageContext:
    """Resolved per-message context handed to every discovery extractor.

    ``seed_root_id`` / ``depth_from_root`` describe the *observed-in* group's
    position in the discovery tree (from ``storage.group_lineage``); E2 derives
    a new mention's depth as ``depth_from_root + 1``.
    """

    text: str
    source_id: UUID
    observed_by_collector_id: UUID
    observed_in_group_id: UUID
    seed_root_id: UUID | None
    depth_from_root: int
    mentioning_actor_id: UUID
    evidence_ref: str
    sent_at_source: datetime
    collected_at: datetime


class DiscoveryExtractor(ABC):
    """A per-message extractor that writes discovery storage as a side effect."""

    name: ClassVar[str]

    @abstractmethod
    async def process(self, ctx: MessageContext, storage: BaseRepository) -> int:
        """Run over one message; return the number of storage rows written.

        Implementations MUST be idempotent at the storage layer (the same
        message re-delivered must not double-count) — both
        ``put_infrastructure_artifact`` and ``record_candidate_mention``
        already guarantee this on their natural keys.
        """


__all__ = ["DiscoveryExtractor", "MessageContext"]
