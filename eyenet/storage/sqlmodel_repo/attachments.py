# SPDX-License-Identifier: AGPL-3.0-or-later
"""AttachmentsMixin — put / get / reclassify rows on AttachmentTable."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import func
from sqlmodel import col, select
from sqlmodel.sql.expression import SelectOfScalar

from eyenet.contracts.audit_subjects import AuditSubject
from eyenet.contracts.enums import SensitivityTier
from eyenet.contracts.message import AttachmentRow
from eyenet.models.message import AttachmentTable
from eyenet.storage.errors import ReclassifyDemotionError
from eyenet.storage.reclassify import ReclassifyOutcome

from ._helpers import TIER_RANK, audit_or_warn, build_audit_row, safe_session

_MIN_REASON_LEN = 16


class AttachmentsMixin:
    async def put_attachment(self, attachment_row: object) -> UUID:
        row = cast("AttachmentRow", attachment_row)
        table = AttachmentTable(**row.model_dump())
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            session.add(table)
            await session.commit()
            await session.refresh(table)
            return table.id

    async def get_attachment(self, attachment_id: UUID) -> AttachmentRow | None:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            table = await session.get(AttachmentTable, attachment_id)
            if table is None:
                return None
            return AttachmentRow.model_validate(table.model_dump())

    def _attachments_filtered_stmt(self, *, mime: str | None) -> SelectOfScalar[AttachmentTable]:
        stmt = select(AttachmentTable)
        if mime is not None:
            stmt = stmt.where(AttachmentTable.mime == mime)
        return stmt

    async def list_attachments(
        self,
        *,
        mime: str | None = None,
        limit: int,
        offset: int = 0,
    ) -> list[AttachmentRow]:
        """Attachments newest-first for the M10 viewer table. Attachments carry
        no own timestamp (the parent message does), and ``id`` is uuid7 =
        time-ordered, so ``id DESC`` is the newest-first sort. Generic ORM
        SELECT — no dialect leak ([[feedback_no_dialect_leak_in_mixins]])."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = (
                self._attachments_filtered_stmt(mime=mime)
                .order_by(col(AttachmentTable.id).desc())
                .offset(offset)
                .limit(limit)
            )
            result = await session.exec(stmt)
            return [AttachmentRow.model_validate(r.model_dump()) for r in list(result)]

    async def count_attachments(self, *, mime: str | None = None) -> int:
        """Count attachments matching the same filter as :meth:`list_attachments`."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            inner = self._attachments_filtered_stmt(mime=mime).subquery()
            result = await session.exec(select(func.count()).select_from(inner))
            return int(result.one())

    async def set_attachment_classification(
        self,
        attachment_id: UUID,
        tier: SensitivityTier,
    ) -> None:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            row = await session.get(AttachmentTable, attachment_id)
            if row is None:
                raise ValueError(f"attachment {attachment_id} not found")
            row.classifier_tier = tier
            session.add(row)
            await session.commit()

    async def reclassify_attachment(
        self,
        *,
        attachment_id: UUID,
        new_tier: SensitivityTier,
        operator_user_id: UUID,
        reason: str,
        grant_id: UUID,
        operator_signature_pubkey_fingerprint: str,
        viewing_context: str | None = None,
        case_refs: list[UUID] | None = None,
        now: datetime | None = None,
        service: str,
        instance_id: str,
        trace_id: str | None = None,
        span_id: str | None = None,
    ) -> ReclassifyOutcome:
        if len(reason) < _MIN_REASON_LEN:
            raise ValueError("reclassify reason must be at least 16 characters")
        at = now or datetime.now(tz=UTC)
        case_ref_strs = [str(c) for c in (case_refs or [])]
        rejection_payload: dict[str, Any] | None = None
        success_payload: dict[str, Any] | None = None
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            row = await session.get(AttachmentTable, attachment_id)
            if row is None:
                raise ValueError(f"attachment {attachment_id} not found")
            classifier_tier = row.classifier_tier
            content_hash = row.sha256
            prior_effective = row.operator_tier_override or classifier_tier
            if TIER_RANK[new_tier] < TIER_RANK[prior_effective]:
                rejection_payload = {
                    "subject_id": str(attachment_id),
                    "subject_kind": "attachment",
                    "content_hash": content_hash,
                    "attempted_tier": new_tier.value,
                    "current_effective_tier": prior_effective.value,
                    "rejection_reason": "would_demote",
                    "user_id": str(operator_user_id),
                    "grant_id": str(grant_id),
                    "reason": reason,
                }
            elif new_tier is prior_effective:
                pass
            else:
                row.operator_tier_override = new_tier
                session.add(row)
                await session.commit()
                await session.refresh(row)
                success_payload = {
                    "blob_id": str(attachment_id),
                    "content_hash": content_hash,
                    "user_id": str(operator_user_id),
                    "grant_id": str(grant_id),
                    "prior_effective_tier": prior_effective.value,
                    "new_tier": new_tier.value,
                    "classifier_tier": classifier_tier.value,
                    "reason": reason,
                    "viewing_context": viewing_context,
                    "operator_signature_pubkey_fingerprint": operator_signature_pubkey_fingerprint,
                    "case_refs": case_ref_strs,
                }
            final_override = row.operator_tier_override
        if rejection_payload is not None:
            await audit_or_warn(
                self,  # type: ignore[arg-type]
                build_audit_row(
                    event=AuditSubject.RECLASSIFY_REJECTED,
                    actor=operator_user_id,
                    subject_kind="attachment",
                    subject_id=attachment_id,
                    payload=rejection_payload,
                    at=at,
                    service=service,
                    instance_id=instance_id,
                    trace_id=trace_id,
                    span_id=span_id,
                ),
                helper="attachments.reclassify",
                domain_id=attachment_id,
            )
            raise ReclassifyDemotionError(
                f"attachment {attachment_id}: cannot demote "
                f"{rejection_payload['current_effective_tier']} -> {new_tier.value}"
            )
        audit_event_id: UUID | None = None
        if success_payload is not None:
            audit_row = build_audit_row(
                event=AuditSubject.RECLASSIFY_ATTACHMENT,
                actor=operator_user_id,
                subject_kind="attachment",
                subject_id=attachment_id,
                payload=success_payload,
                at=at,
                service=service,
                instance_id=instance_id,
                trace_id=trace_id,
                span_id=span_id,
            )
            audit_event_id = cast("UUID", audit_row["id"])
            await audit_or_warn(
                self,  # type: ignore[arg-type]
                audit_row,
                helper="attachments.reclassify",
                domain_id=attachment_id,
            )
        return ReclassifyOutcome(
            prior_effective_tier=prior_effective,
            classifier_tier=classifier_tier,
            operator_tier_override=final_override,
            effective_tier=final_override or classifier_tier,
            reclassified_at=at,
            audit_event_id=audit_event_id,
        )


__all__ = ["AttachmentsMixin"]
