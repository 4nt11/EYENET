# SPDX-License-Identifier: AGPL-3.0-or-later
"""ObservationsMixin — put / latest / by_evidence / reclassify."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from opentelemetry import trace
from sqlmodel import col, select

from eyenet.contracts.audit_subjects import AuditSubject
from eyenet.contracts.enums import SensitivityTier
from eyenet.contracts.observation import ObservationRow
from eyenet.models import ObservationTable
from eyenet.storage.errors import ReclassifyDemotionError

from ._helpers import TIER_RANK, audit_or_warn, build_audit_row, safe_session

_tracer = trace.get_tracer("eyenet.storage.sqlmodel_repo.observations")
_MIN_REASON_LEN = 16


class ObservationsMixin:
    async def put_observation(self, observation_row: object) -> None:
        row = cast("ObservationRow", observation_row)
        table = ObservationTable(**row.model_dump())
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            session.add(table)
            await session.commit()

    async def latest_observations(
        self,
        actor_id: UUID,
        primitive_name: str,
        limit: int = 1,
    ) -> list[object]:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = (
                select(ObservationTable)
                .where(ObservationTable.actor_id == actor_id)
                .where(ObservationTable.primitive_name == primitive_name)
                .order_by(col(ObservationTable.observed_at).desc())
                .limit(limit)
            )
            result = await session.exec(stmt)
            return list(result)

    async def observation_by_evidence_and_primitive(
        self,
        evidence_ref: str,
        primitive_name: str,
    ) -> object | None:
        with _tracer.start_as_current_span(
            "storage.observations.by_evidence",
            attributes={
                "message.evidence_ref": evidence_ref,
                "primitive.name": primitive_name,
            },
        ) as by_evidence_span:
            async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
                result = await session.exec(
                    select(ObservationTable)
                    .where(ObservationTable.evidence_ref == evidence_ref)
                    .where(ObservationTable.primitive_name == primitive_name)
                    .order_by(col(ObservationTable.observed_at).desc())
                )
                row = result.first()
                by_evidence_span.set_attribute("result.found", row is not None)
                return row

    async def reclassify_observation(
        self,
        *,
        observation_id: UUID,
        new_tier: SensitivityTier,
        operator_user_id: UUID,
        reason: str,
        now: datetime | None = None,
        service: str,
        instance_id: str,
        trace_id: str | None = None,
        span_id: str | None = None,
    ) -> ObservationTable:
        if len(reason) < _MIN_REASON_LEN:
            raise ValueError("reclassify reason must be at least 16 characters")
        at = now or datetime.now(tz=UTC)
        rejection_payload: dict[str, Any] | None = None
        success_payload: dict[str, Any] | None = None
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            row = await session.get(ObservationTable, observation_id)
            if row is None:
                raise ValueError(f"observation {observation_id} not found")
            current_effective = row.operator_tier_override or row.classifier_tier
            if TIER_RANK[new_tier] < TIER_RANK[current_effective]:
                rejection_payload = {
                    "observation_id": str(observation_id),
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
                    "observation_id": str(observation_id),
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
                    subject_kind="observation",
                    subject_id=observation_id,
                    payload=rejection_payload,
                    at=at,
                    service=service,
                    instance_id=instance_id,
                    trace_id=trace_id,
                    span_id=span_id,
                ),
                helper="observations.reclassify",
                domain_id=observation_id,
            )
            raise ReclassifyDemotionError(
                f"observation {observation_id}: cannot demote "
                f"{rejection_payload['from']} → {rejection_payload['to']}"
            )
        if success_payload is not None:
            await audit_or_warn(
                self,  # type: ignore[arg-type]
                build_audit_row(
                    event=AuditSubject.RECLASSIFY_OBSERVATION,
                    actor=operator_user_id,
                    subject_kind="observation",
                    subject_id=observation_id,
                    payload=success_payload,
                    at=at,
                    service=service,
                    instance_id=instance_id,
                    trace_id=trace_id,
                    span_id=span_id,
                ),
                helper="observations.reclassify",
                domain_id=observation_id,
            )
        return updated


__all__ = ["ObservationsMixin"]
