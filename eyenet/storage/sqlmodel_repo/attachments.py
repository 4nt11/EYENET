# SPDX-License-Identifier: AGPL-3.0-or-later
"""AttachmentsMixin — put / get / reclassify rows on AttachmentTable."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from eyenet.contracts.audit_subjects import AuditSubject
from eyenet.contracts.enums import SensitivityTier
from eyenet.contracts.message import AttachmentRow
from eyenet.models.message import AttachmentTable
from eyenet.storage.errors import ReclassifyDemotionError

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
        now: datetime | None = None,
        service: str,
        instance_id: str,
        trace_id: str | None = None,
        span_id: str | None = None,
    ) -> AttachmentTable:
        if len(reason) < _MIN_REASON_LEN:
            raise ValueError("reclassify reason must be at least 16 characters")
        at = now or datetime.now(tz=UTC)
        rejection_payload: dict[str, Any] | None = None
        success_payload: dict[str, Any] | None = None
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            row = await session.get(AttachmentTable, attachment_id)
            if row is None:
                raise ValueError(f"attachment {attachment_id} not found")
            current_effective = row.operator_tier_override or row.classifier_tier
            if TIER_RANK[new_tier] < TIER_RANK[current_effective]:
                rejection_payload = {
                    "attachment_id": str(attachment_id),
                    "from": current_effective.value,
                    "to": new_tier.value,
                    "reason": reason,
                }
            elif new_tier is current_effective:
                pass
            else:
                row.operator_tier_override = new_tier
                session.add(row)
                await session.commit()
                await session.refresh(row)
                success_payload = {
                    "attachment_id": str(attachment_id),
                    "from": current_effective.value,
                    "to": new_tier.value,
                    "reason": reason,
                }
            updated = row
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
                f"{rejection_payload['from']} → {rejection_payload['to']}"
            )
        if success_payload is not None:
            await audit_or_warn(
                self,  # type: ignore[arg-type]
                build_audit_row(
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
                ),
                helper="attachments.reclassify",
                domain_id=attachment_id,
            )
        return updated


__all__ = ["AttachmentsMixin"]
