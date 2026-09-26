# SPDX-License-Identifier: AGPL-3.0-or-later
"""MessagesMixin — body store + put_message + resolve_message_id.

Per PLAN §4.3 / §5.2: bus envelopes carry hashes + `evidence_ref` only;
this mixin holds the bodies. Every body dereference triggers an audit
event in the calling service.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

import structlog
from opentelemetry import trace
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select

from eyenet.models import ContentTemplateTable, MessageTable

from ._helpers import safe_session

_log = structlog.get_logger()
_tracer = trace.get_tracer("eyenet.storage.sqlmodel_repo.messages")


@dataclass
class _TemplateGroup:
    """In-memory accumulator for one content-template fingerprint during the
    copypasta batch pass."""

    sample: str
    char_len: int
    first: datetime
    last: datetime
    msg_ids: list[UUID] = field(default_factory=list)
    actors: set[UUID] = field(default_factory=set)


class MessagesMixin:
    async def get_message_body(self, evidence_ref: str) -> bytes | None:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            result = await session.exec(
                select(MessageTable.body).where(MessageTable.evidence_ref == evidence_ref)
            )
            row = result.first()
            if row is None:
                return None
            return str(row).encode("utf-8")

    async def get_message_id_by_evidence_ref(
        self,
        evidence_ref: str,
    ) -> UUID | None:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            result = await session.exec(
                select(MessageTable.id).where(MessageTable.evidence_ref == evidence_ref)
            )
            row = result.first()
            if row is None:
                return None
            return UUID(str(row))

    async def messages_by_evidence_refs(
        self,
        evidence_refs: list[str],
    ) -> dict[str, tuple[UUID, str]]:
        """Bulk-fetch (message_id, body) for many evidence_refs in ONE query — the
        incident classifier's batch flush. Refs with no message row are omitted."""
        if not evidence_refs:
            return {}
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            result = await session.exec(
                select(
                    MessageTable.evidence_ref, MessageTable.id, MessageTable.body
                ).where(col(MessageTable.evidence_ref).in_(evidence_refs))
            )
            return {
                str(ref): (UUID(str(mid)), str(body)) for ref, mid, body in result.all()
            }

    async def put_message(
        self,
        row: object,
        attachments: list[object] | None = None,
    ) -> bool:
        """Persist message + attachment rows in one transaction.

        `row` and items in `attachments` are SQLModel table instances;
        callers construct them from contract rows or directly.
        """

        msg = row  # type-erased; sqlmodel handles whichever concrete table
        evidence_ref = getattr(msg, "evidence_ref", None)
        with _tracer.start_as_current_span(
            "storage.messages.put_message",
            attributes={
                "message.evidence_ref": evidence_ref or "",
                "message.attachment_count": len(attachments or []),
            },
        ) as put_span:
            try:
                async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
                    session.add(msg)
                    await session.flush()
                    for att in attachments or []:
                        session.add(att)
                    await session.commit()
                put_span.set_attribute("message.inserted", True)
                return True
            except IntegrityError:
                put_span.set_attribute("message.inserted", False)
                _log.debug("message.duplicate", evidence_ref=evidence_ref)
                return False

    async def recent_message_bodies_for_actor(
        self,
        actor_id: UUID,
        *,
        limit: int,
    ) -> list[str]:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            result = await session.exec(
                select(MessageTable.body)
                .where(MessageTable.actor_id == actor_id)
                .order_by(col(MessageTable.sent_at_source).desc())
                .order_by(col(MessageTable.id).desc())
                .limit(limit)
            )
            rows = list(result.all())
        rows.reverse()
        return [str(b) for b in rows if b]

    async def flagged_copypasta_fingerprints(self) -> set[str]:
        """Fingerprints of templates currently flagged as copypasta (sensor gate)."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            result = await session.exec(
                select(ContentTemplateTable.fingerprint).where(
                    col(ContentTemplateTable.is_copypasta).is_(True)
                )
            )
            return {str(fp) for fp in result.all()}

    async def detect_copypasta_templates(self) -> int:
        """Batch: group stored message bodies by masked fingerprint, upsert a
        ``content_template`` per group, and tag each message with its template.
        Templates crossing the copypasta thresholds get ``is_copypasta=True`` and
        their messages' ``template_id`` set. Returns the flagged-template count.

        ponytail: one full pass over message bodies (small-operator scale). The
        streaming form (fingerprint on ingest) is the upgrade in the spec.
        """
        from eyenet.linker.copypasta import (  # noqa: PLC0415 — pure helper, avoids storage->linker at import
            is_copypasta,
            normalize_for_template,
            template_fingerprint,
        )

        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            rows = (
                await session.exec(
                    select(
                        MessageTable.id,
                        MessageTable.actor_id,
                        MessageTable.body,
                        MessageTable.ingested_at,
                    ).where(col(MessageTable.body).is_not(None))
                )
            ).all()

        groups: dict[str, _TemplateGroup] = {}
        for msg_id, actor_id, body, ingested_at in rows:
            if not body:
                continue
            fp = template_fingerprint(body)
            g = groups.get(fp)
            if g is None:
                g = _TemplateGroup(
                    sample=body,
                    char_len=len(normalize_for_template(body)),
                    first=ingested_at,
                    last=ingested_at,
                )
                groups[fp] = g
            g.msg_ids.append(msg_id)
            g.actors.add(actor_id)
            g.first = min(g.first, ingested_at)
            g.last = max(g.last, ingested_at)

        flagged = 0
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            for fp, g in groups.items():
                flag = is_copypasta(g.char_len, len(g.actors))
                existing = (
                    await session.exec(
                        select(ContentTemplateTable).where(
                            col(ContentTemplateTable.fingerprint) == fp
                        )
                    )
                ).first()
                if existing is None:
                    tmpl = ContentTemplateTable(
                        fingerprint=fp,
                        char_len=g.char_len,
                        occurrence_count=len(g.msg_ids),
                        distinct_actor_count=len(g.actors),
                        is_copypasta=flag,
                        sample_body=g.sample[:4000],
                        first_seen_at_ingest=g.first,
                        last_seen_at_ingest=g.last,
                    )
                    session.add(tmpl)
                    await session.flush()
                else:
                    existing.occurrence_count = len(g.msg_ids)
                    existing.distinct_actor_count = len(g.actors)
                    existing.is_copypasta = flag
                    existing.last_seen_at_ingest = g.last
                    session.add(existing)
                    tmpl = existing
                if flag:
                    flagged += 1
                    for msg_id in g.msg_ids:
                        m = await session.get(MessageTable, msg_id)
                        if m is not None:
                            m.template_id = tmpl.id
                            session.add(m)
            await session.commit()
        return flagged

    async def message_bodies_by_actor(self) -> dict[UUID, list[str]]:
        """All non-empty message bodies grouped by author actor_id.

        Generic (ANSI) SELECT; used by the shared-infrastructure linker's batch
        pass. Small-operator scale — one query, grouped in Python.
        """
        out: dict[UUID, list[str]] = {}
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            result = await session.exec(
                select(MessageTable.actor_id, MessageTable.body).where(
                    col(MessageTable.body).is_not(None)
                )
            )
            for actor_id, body in result.all():
                if body:
                    out.setdefault(actor_id, []).append(str(body))
        return out

    async def messages_for_actor(
        self,
        actor_id: UUID,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int,
        offset: int = 0,
    ) -> list[object]:
        """Messages sent by an actor, newest-first (M9.F1 timeline).

        Optional half-open time window on ``sent_at_source``. Returns
        ``MessageTable`` rows (type-erased to ``object``) for the timeline
        projector — unlike ``recent_message_bodies_for_actor`` which yields
        only bodies, the timeline needs the row's id and timestamp.
        """
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = select(MessageTable).where(MessageTable.actor_id == actor_id)
            if since is not None:
                stmt = stmt.where(col(MessageTable.sent_at_source) >= since)
            if until is not None:
                stmt = stmt.where(col(MessageTable.sent_at_source) < until)
            stmt = (
                stmt.order_by(col(MessageTable.sent_at_source).desc())
                .order_by(col(MessageTable.id).desc())
                .limit(limit)
                .offset(offset)
            )
            result = await session.exec(stmt)
            return list(result)

    async def count_messages_for_actor(
        self,
        actor_id: UUID,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> int:
        """Count messages for an actor, with the same optional window (M9.F1)."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = (
                select(func.count())
                .select_from(MessageTable)
                .where(MessageTable.actor_id == actor_id)
            )
            if since is not None:
                stmt = stmt.where(col(MessageTable.sent_at_source) >= since)
            if until is not None:
                stmt = stmt.where(col(MessageTable.sent_at_source) < until)
            result = await session.exec(stmt)
            return int(result.one())

    async def resolve_message_id(
        self,
        *,
        source_id: UUID,
        group_id: UUID,
        platform_msgid: str,
    ) -> UUID | None:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            result = await session.exec(
                select(MessageTable.id).where(
                    MessageTable.source_id == source_id,
                    MessageTable.group_id == group_id,
                    MessageTable.platform_msgid == platform_msgid,
                )
            )
            row = result.first()
            if row is None:
                return None
            return UUID(str(row))


__all__ = ["MessagesMixin"]
