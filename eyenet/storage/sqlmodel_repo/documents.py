# SPDX-License-Identifier: AGPL-3.0-or-later
"""DocumentsMixin — put / get rows on DocumentTable.

Generic SQLModel ORM only (SELECT-then-add / session.get) — no dialect-specific
SQL, so MySQL/Postgres backends inherit this unchanged ([[feedback_no_dialect_leak_in_mixins]]).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from eyenet.contracts.audit_subjects import AuditSubject
from eyenet.contracts.document import DocumentRow
from eyenet.models.document import DocumentTable
from eyenet.storage.errors import ReclassifyDemotionError
from eyenet.storage.reclassify import ReclassifyOutcome

from ._helpers import TIER_RANK, audit_or_warn, build_audit_row, safe_session

if TYPE_CHECKING:
    from eyenet.contracts.enums import SensitivityTier

_MIN_REASON_LEN = 16


class DocumentsMixin:
    async def put_document(self, document_row: object) -> UUID:
        row = cast("DocumentRow", document_row)
        table = DocumentTable(**row.model_dump())
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            session.add(table)
            await session.commit()
            await session.refresh(table)
            return table.id

    async def get_document(self, document_id: UUID) -> DocumentRow | None:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            table = await session.get(DocumentTable, document_id)
            if table is None:
                return None
            return DocumentRow.model_validate(table.model_dump())

    async def settle_document_classification(
        self,
        document_id: UUID,
        *,
        tier: SensitivityTier,
        doc_kind: str | None,
        extracted_text: str | None,
        embedded_meta: dict[str, Any],
        classification: dict[str, Any],
        review_required: bool,
        ingested_at: datetime,
    ) -> None:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            row = await session.get(DocumentTable, document_id)
            if row is None:
                raise ValueError(f"document {document_id} not found")
            row.classifier_tier = tier
            row.doc_kind = doc_kind
            row.extracted_text = extracted_text
            row.embedded_meta = embedded_meta
            row.classification = classification
            row.review_required = review_required
            row.ingested_at = ingested_at
            session.add(row)
            await session.commit()

    async def reclassify_document(
        self,
        *,
        document_id: UUID,
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
            row = await session.get(DocumentTable, document_id)
            if row is None:
                raise ValueError(f"document {document_id} not found")
            classifier_tier = row.classifier_tier
            content_hash = row.sha256
            prior_effective = row.operator_tier_override or classifier_tier
            if TIER_RANK[new_tier] < TIER_RANK[prior_effective]:
                rejection_payload = {
                    "subject_id": str(document_id),
                    "subject_kind": "document",
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
                    "document_id": str(document_id),
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
                    subject_kind="document",
                    subject_id=document_id,
                    payload=rejection_payload,
                    at=at,
                    service=service,
                    instance_id=instance_id,
                    trace_id=trace_id,
                    span_id=span_id,
                ),
                helper="documents.reclassify",
                domain_id=document_id,
            )
            raise ReclassifyDemotionError(
                f"document {document_id}: cannot demote "
                f"{rejection_payload['current_effective_tier']} -> {new_tier.value}"
            )
        audit_event_id: UUID | None = None
        if success_payload is not None:
            audit_row = build_audit_row(
                event=AuditSubject.RECLASSIFY_DOCUMENT,
                actor=operator_user_id,
                subject_kind="document",
                subject_id=document_id,
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
                helper="documents.reclassify",
                domain_id=document_id,
            )
        return ReclassifyOutcome(
            prior_effective_tier=prior_effective,
            classifier_tier=classifier_tier,
            operator_tier_override=final_override,
            effective_tier=final_override or classifier_tier,
            reclassified_at=at,
            audit_event_id=audit_event_id,
        )


__all__ = ["DocumentsMixin"]
