# SPDX-License-Identifier: AGPL-3.0-or-later
"""ObservationsMixin — put / latest / by_evidence / reclassify."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from opentelemetry import trace
from sqlalchemy import func
from sqlmodel import col, select

from eyenet.contracts.audit_subjects import AuditSubject
from eyenet.contracts.enums import SensitivityTier
from eyenet.contracts.observation import ObservationRow
from eyenet.models import ObservationTable
from eyenet.storage.errors import ReclassifyDemotionError
from eyenet.storage.reclassify import ReclassifyOutcome

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

    async def put_observations_bulk(self, observation_rows: list[object]) -> None:
        """Persist many ObservationRows in ONE session. Used by the
        StylometricSensor dispatch loop to amortize per-primitive session
        overhead under the async pool."""
        if not observation_rows:
            return
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            for r in observation_rows:
                row = cast("ObservationRow", r)
                session.add(ObservationTable(**row.model_dump()))
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

    async def observations_for_actor(
        self,
        actor_id: UUID,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int,
        offset: int = 0,
    ) -> list[object]:
        """Observations attributable to an actor, newest-first (M9.F1).

        Optional half-open time window on ``observed_at`` (``since <= ts``,
        ``ts < until``). Returns ``ObservationTable`` rows for the API
        projector; type-erased to ``object`` to keep ORM types off the ABC.
        """
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = select(ObservationTable).where(ObservationTable.actor_id == actor_id)
            if since is not None:
                stmt = stmt.where(col(ObservationTable.observed_at) >= since)
            if until is not None:
                stmt = stmt.where(col(ObservationTable.observed_at) < until)
            stmt = (
                stmt.order_by(col(ObservationTable.observed_at).desc())
                .order_by(col(ObservationTable.id).desc())
                .limit(limit)
                .offset(offset)
            )
            result = await session.exec(stmt)
            return list(result)

    async def count_observations_for_actor(
        self,
        actor_id: UUID,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> int:
        """Count observations for an actor, with the same optional window (M9.F1)."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = (
                select(func.count())
                .select_from(ObservationTable)
                .where(ObservationTable.actor_id == actor_id)
            )
            if since is not None:
                stmt = stmt.where(col(ObservationTable.observed_at) >= since)
            if until is not None:
                stmt = stmt.where(col(ObservationTable.observed_at) < until)
            result = await session.exec(stmt)
            return int(result.one())

    async def count_observations(self) -> int:
        """Total number of observations across all actors (M9.F3 graph stats)."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            result = await session.exec(select(func.count()).select_from(ObservationTable))
            return int(result.one())

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
            row = await session.get(ObservationTable, observation_id)
            if row is None:
                raise ValueError(f"observation {observation_id} not found")
            classifier_tier = row.classifier_tier
            prior_effective = row.operator_tier_override or classifier_tier
            if TIER_RANK[new_tier] < TIER_RANK[prior_effective]:
                rejection_payload = {
                    "subject_id": str(observation_id),
                    "subject_kind": "observation",
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
                    "observation_id": str(observation_id),
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
                f"{rejection_payload['current_effective_tier']} -> {new_tier.value}"
            )
        audit_event_id: UUID | None = None
        if success_payload is not None:
            audit_row = build_audit_row(
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
            )
            audit_event_id = cast("UUID", audit_row["id"])
            await audit_or_warn(
                self,  # type: ignore[arg-type]
                audit_row,
                helper="observations.reclassify",
                domain_id=observation_id,
            )
        return ReclassifyOutcome(
            prior_effective_tier=prior_effective,
            classifier_tier=classifier_tier,
            operator_tier_override=final_override,
            effective_tier=final_override or classifier_tier,
            reclassified_at=at,
            audit_event_id=audit_event_id,
        )


__all__ = ["ObservationsMixin"]
