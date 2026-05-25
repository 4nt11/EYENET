# SPDX-License-Identifier: AGPL-3.0-or-later
"""MessagesMixin — body store + put_message + resolve_message_id.

Per PLAN §4.3 / §5.2: bus envelopes carry hashes + `evidence_ref` only;
this mixin holds the bodies. Every body dereference triggers an audit
event in the calling service.
"""

from __future__ import annotations

from uuid import UUID

import structlog
from opentelemetry import trace
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from eyenet.models import MessageTable

from ._helpers import safe_session

_log = structlog.get_logger()
_tracer = trace.get_tracer("eyenet.storage.sqlmodel_repo.messages")


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
