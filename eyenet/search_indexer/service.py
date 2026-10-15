# SPDX-License-Identifier: AGPL-3.0-or-later
"""SearchIndexerService — live, event-driven maintenance of search_document.

Subscribes (queue_group ``search`` for horizontal fan-out) to:
  * ``entity.>``                     — change-gated actor/group/case events
  * ``raw.message.>``                — per-message indexing
  * ``attribution.persona.updated``  — persona reindex
  * ``classify.document.uploaded``   — document reindex

Each handler reindexes exactly the one entity named in the envelope, building its
payload with the shared ``haystack`` builders (identical to the backfill). Reads
message bodies straight off ``MessageTable.body`` (a column, not the audited
evidence-deref path), so indexing does NOT emit audit events. Handler failures
are logged and swallowed — a reindex miss must never wedge the bus subscriber.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import func
from sqlmodel import col, select

from eyenet.contracts.attribution import SUBJECT_PERSONA_UPDATED, PersonaUpdatedEnvelope
from eyenet.contracts.classify_events import SUBJECT_DOCUMENT_UPLOADED, DocumentUploadedEnvelope
from eyenet.contracts.enums import GroupKind
from eyenet.contracts.raw_message import RawMessageEnvelope
from eyenet.contracts.search_events import SUBJECT_ENTITY_PREFIX, EntityChangedEnvelope
from eyenet.models import (
    ActorAliasHistoryTable,
    ActorTable,
    CaseTable,
    CollectorGroupMembershipTable,
    DocumentTable,
    GroupCandidateTable,
    GroupTable,
    InfrastructureArtifactTable,
    MessageTable,
    PersonaTable,
)
from eyenet.search_indexer import haystack
from eyenet.service import ServiceBase
from eyenet.telemetry.logging import get_logger
from eyenet.telemetry.propagation import attach_from_headers

if TYPE_CHECKING:
    from eyenet.contracts.bus import Bus
    from eyenet.storage.repository import BaseRepository

_log = get_logger()


class SearchIndexerService(ServiceBase):
    """Keeps the global-search index fresh off the bus (GLOBAL_SEARCH.md §2.4)."""

    def __init__(
        self, *, bus: Bus, storage: BaseRepository, instance_id: str = "search_indexer_1"
    ) -> None:
        super().__init__(bus=bus, storage=storage)
        self._instance_id = instance_id

    @property
    def name(self) -> str:
        return "search_indexer"

    @property
    def instance_id(self) -> str:
        return self._instance_id

    async def on_subscribe(self) -> None:
        async def _on_entity(_s: str, p: bytes, h: dict[str, str]) -> None:
            asyncio.create_task(self._process(self._handle_entity, p, h))  # noqa: RUF006

        async def _on_message(_s: str, p: bytes, h: dict[str, str]) -> None:
            asyncio.create_task(self._process(self._handle_message, p, h))  # noqa: RUF006

        async def _on_persona(_s: str, p: bytes, h: dict[str, str]) -> None:
            asyncio.create_task(self._process(self._handle_persona, p, h))  # noqa: RUF006

        async def _on_document(_s: str, p: bytes, h: dict[str, str]) -> None:
            asyncio.create_task(self._process(self._handle_document, p, h))  # noqa: RUF006

        await self._bus.subscribe(f"{SUBJECT_ENTITY_PREFIX}>", _on_entity, queue_group="search")
        await self._bus.subscribe("raw.message.>", _on_message, queue_group="search")
        await self._bus.subscribe(SUBJECT_PERSONA_UPDATED, _on_persona, queue_group="search")
        await self._bus.subscribe(SUBJECT_DOCUMENT_UPLOADED, _on_document, queue_group="search")
        _log.info("search_indexer.subscribed", instance_id=self.instance_id)

    async def _process(self, handler: object, payload: bytes, headers: dict[str, str]) -> None:
        # Tracing attach INSIDE the task body (the create_task runs later, §4.5).
        with attach_from_headers(headers):
            try:
                await handler(payload)  # type: ignore[operator]
            except Exception as exc:
                _log.error("search_indexer.handler_error", error=str(exc))

    # -- handlers -----------------------------------------------------------
    async def _handle_entity(self, payload: bytes) -> None:
        env = EntityChangedEnvelope.model_validate_json(payload)
        if env.entity_type == "actor":
            await self._reindex_actor(env.entity_id)
        elif env.entity_type == "group":
            await self._reindex_group(env.entity_id)
        elif env.entity_type == "case":
            await self._reindex_case(env.entity_id)
        elif env.entity_type == "artifact":
            await self._reindex_artifact(env.entity_id)
        else:
            _log.warning("search_indexer.unknown_entity_type", entity_type=env.entity_type)

    async def _handle_message(self, payload: bytes) -> None:
        env = RawMessageEnvelope.model_validate_json(payload)
        await self._reindex_message(env.evidence_ref)

    async def _handle_persona(self, payload: bytes) -> None:
        env = PersonaUpdatedEnvelope.model_validate_json(payload)
        await self._reindex_persona(env.persona_id)

    async def _handle_document(self, payload: bytes) -> None:
        env = DocumentUploadedEnvelope.model_validate_json(payload)
        await self._reindex_document(env.document_id)

    # -- reindexers ---------------------------------------------------------
    async def _reindex_actor(self, actor_id: UUID) -> None:
        async with self._storage.session() as s:
            actor = await s.get(ActorTable, actor_id)
            if actor is None:
                return
            aliases = list(
                await s.exec(
                    select(ActorAliasHistoryTable.value).where(
                        ActorAliasHistoryTable.actor_id == actor_id
                    )
                )
            )
        await self._storage.put_search_document(**haystack.actor_doc(actor, aliases))

    async def _reindex_artifact(self, artifact_id: UUID) -> None:
        async with self._storage.session() as s:
            artifact = await s.get(InfrastructureArtifactTable, artifact_id)
            if artifact is None:
                return
        await self._storage.put_search_document(**haystack.artifact_doc(artifact))

    async def _reindex_group(self, group_id: UUID) -> None:
        async with self._storage.session() as s:
            group = await s.get(GroupTable, group_id)
            if group is not None:
                if group.kind == GroupKind.FORUM_THREAD:
                    doc = await self._thread_doc(s, group)
                else:
                    open_m = (
                        await s.exec(
                            select(CollectorGroupMembershipTable.id).where(
                                CollectorGroupMembershipTable.group_id == group_id,
                                col(CollectorGroupMembershipTable.left_at).is_(None),
                            )
                        )
                    ).first()
                    doc = haystack.group_doc(group, status="joined" if open_m else "known")
            else:
                candidate = await s.get(GroupCandidateTable, group_id)
                if candidate is None:
                    return
                doc = haystack.candidate_group_doc(candidate)
        await self._storage.put_search_document(**doc)

    async def _thread_doc(self, s: object, group: GroupTable) -> dict[str, object]:
        """Build a forum-thread doc: OP = earliest message in the thread, + post count."""
        op = (
            await s.exec(  # type: ignore[attr-defined]
                select(MessageTable)
                .where(MessageTable.group_id == group.id)
                .order_by(col(MessageTable.sent_at_source))
                .limit(1)
            )
        ).first()
        post_count = (
            await s.exec(  # type: ignore[attr-defined]
                select(func.count())
                .select_from(MessageTable)
                .where(MessageTable.group_id == group.id)
            )
        ).one()
        op_author = await s.get(ActorTable, op.actor_id) if op is not None else None  # type: ignore[attr-defined]
        handle = (op_author.current_handle or op_author.current_display_name) if op_author else None
        return haystack.thread_doc(
            group, op=op, op_author_handle=handle, post_count=int(post_count)
        )

    async def _reindex_case(self, case_id: UUID) -> None:
        async with self._storage.session() as s:
            case = await s.get(CaseTable, case_id)
            if case is None:
                return
        await self._storage.put_search_document(**haystack.case_doc(case))

    async def _reindex_message(self, evidence_ref: str) -> None:
        async with self._storage.session() as s:
            message = (
                await s.exec(select(MessageTable).where(MessageTable.evidence_ref == evidence_ref))
            ).first()
            if message is None:
                return
            group = await s.get(GroupTable, message.group_id)
            actor = await s.get(ActorTable, message.actor_id)
        await self._storage.put_search_document(
            **haystack.message_doc(
                message,
                group_title=group.current_title if group else None,
                author_handle=(actor.current_handle or actor.current_display_name)
                if actor
                else None,
            )
        )
        # A post in a forum thread may be its OP (new thread) or bump the count —
        # refresh the thread doc so author/created/OP/posts stay current.
        if group is not None and group.kind == GroupKind.FORUM_THREAD:
            await self._reindex_group(group.id)

    async def _reindex_persona(self, persona_id: UUID) -> None:
        async with self._storage.session() as s:
            persona = await s.get(PersonaTable, persona_id)
            if persona is None:
                return
            handles: list[str] = []
            for m in persona.member_actor_ids:
                actor = await s.get(ActorTable, UUID(m))
                if actor is not None:
                    handles.append(actor.current_handle or actor.current_display_name or "")
        await self._storage.put_search_document(**haystack.persona_doc(persona, handles))

    async def _reindex_document(self, document_id: UUID) -> None:
        async with self._storage.session() as s:
            document = await s.get(DocumentTable, document_id)
            if document is None:
                return
        await self._storage.put_search_document(**haystack.document_doc(document))


__all__ = ["SearchIndexerService"]
