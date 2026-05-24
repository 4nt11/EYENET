"""SQLiteMessageStore — `MessageStore` ABC over SQLite.

Per PLAN §4.3 / §5.2: bus envelopes carry hashes + `evidence_ref` only;
this store holds the bodies. Every dereference triggers an audit event in
the calling service (not enforced here — that's `AuditEmitter`'s job).
"""

from __future__ import annotations

from uuid import UUID

import structlog
from opentelemetry import trace
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from eyenet.contracts.storage import MessageStore
from eyenet.models import AttachmentTable, MessageTable

_log = structlog.get_logger()
_tracer = trace.get_tracer("eyenet.storage.messages")


class SQLiteMessageStore(MessageStore):
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    async def get_by_evidence_ref(self, evidence_ref: str) -> bytes | None:
        with Session(self._engine) as session:
            result = session.exec(
                select(MessageTable.body).where(MessageTable.evidence_ref == evidence_ref)
            ).first()
            if result is None:
                return None
            return str(result).encode("utf-8")

    def get_id_by_evidence_ref(self, evidence_ref: str) -> UUID | None:
        with Session(self._engine) as session:
            result = session.exec(
                select(MessageTable.id).where(MessageTable.evidence_ref == evidence_ref)
            ).first()
            if result is None:
                return None
            return UUID(str(result))

    async def put(self, evidence_ref: str, body: bytes) -> None:
        raise NotImplementedError(
            "SQLiteMessageStore.put is not used. Use put_message() for full ingest."
        )

    async def put_message(
        self,
        row: MessageTable,
        attachments: list[AttachmentTable] | None = None,
    ) -> bool:
        """Persist a message row + optional attachment metadata.

        Returns True on insert, False if evidence_ref already exists (idempotent).
        All rows are written in a single transaction.
        """

        with _tracer.start_as_current_span(
            "storage.messages.put_message",
            attributes={
                "source.platform": getattr(row, "platform", "unknown"),
                "message.evidence_ref": row.evidence_ref,
                "message.attachment_count": len(attachments or []),
            },
        ) as put_span:
            try:
                with Session(self._engine, expire_on_commit=False) as session:
                    session.add(row)
                    session.flush()
                    for att in attachments or []:
                        session.add(att)
                    session.commit()
                put_span.set_attribute("message.inserted", True)
                return True
            except IntegrityError:
                put_span.set_attribute("message.inserted", False)
                _log.debug("message.duplicate", evidence_ref=row.evidence_ref)
                return False


__all__ = ["SQLiteMessageStore"]
