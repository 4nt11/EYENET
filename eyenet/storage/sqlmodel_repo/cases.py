# SPDX-License-Identifier: AGPL-3.0-or-later
"""CasesMixin — case lifecycle, members, collaborators, tier recompute."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from eyenet.contracts.audit_subjects import AuditSubject
from eyenet.contracts.case import CaseCollaboratorRow, CaseMemberRow, CaseRow
from eyenet.contracts.enums import (
    AutoJoinPolicy,
    CaseRoleOnCase,
    CaseStatus,
    CaseSubjectKind,
    RedundancyPolicy,
    SensitivityTier,
)
from eyenet.models.candidates import GroupCandidateMentionTable
from eyenet.models.case import CaseCollaboratorTable, CaseMemberTable, CaseTable
from eyenet.models.message import AttachmentTable
from eyenet.models.observation import ObservationTable
from eyenet.storage.errors import CaseError

from ._helpers import RANK_TIER, TIER_RANK, audit_or_warn, build_audit_row, safe_session

_MIN_REASON_LEN = 16
_MIN_TITLE_LEN = 3
_CASE_SUBJECT_KIND = "case"


def _coerce_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _case_row(table: CaseTable) -> CaseRow:
    data = table.model_dump()
    for k in ("created_at", "closed_at", "archived_at"):
        data[k] = _coerce_utc(data.get(k))
    return CaseRow.model_validate(data)


def _member_row(table: CaseMemberTable) -> CaseMemberRow:
    data = table.model_dump()
    data.pop("active_case_id", None)
    for k in ("added_at", "removed_at"):
        data[k] = _coerce_utc(data.get(k))
    return CaseMemberRow.model_validate(data)


def _collab_row(table: CaseCollaboratorTable) -> CaseCollaboratorRow:
    data = table.model_dump()
    data.pop("active_case_id", None)
    for k in ("granted_at", "revoked_at"):
        data[k] = _coerce_utc(data.get(k))
    return CaseCollaboratorRow.model_validate(data)


async def _require_case(session: AsyncSession, case_id: UUID) -> CaseTable:
    table = await session.get(CaseTable, case_id)
    if table is None:
        raise CaseError(f"case {case_id} not found")
    return table


class CasesMixin:
    # -- lifecycle -------------------------------------------------------------

    async def create_case(
        self,
        *,
        title: str,
        description: str | None,
        opened_by_user_id: UUID,
        now: datetime | None = None,
        service: str,
        instance_id: str,
        trace_id: str | None = None,
        span_id: str | None = None,
    ) -> CaseRow:
        if len(title) < _MIN_TITLE_LEN:
            raise CaseError("title must be at least 3 characters")
        created_at = now or datetime.now(tz=UTC)
        table = CaseTable(
            title=title,
            description=description,
            status=CaseStatus.OPEN,
            effective_tier=SensitivityTier.NORMAL,
            created_by_user_id=opened_by_user_id,
            created_at=created_at,
        )
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            session.add(table)
            await session.commit()
            await session.refresh(table)
        row = _case_row(table)
        await self._emit_case_audit(
            event=AuditSubject.CASE_CREATED,
            actor=opened_by_user_id,
            subject_id=row.id,
            payload={"title": title, "created_at": created_at.isoformat()},
            at=created_at,
            service=service,
            instance_id=instance_id,
            trace_id=trace_id,
            span_id=span_id,
        )
        return row

    async def update_case(
        self,
        *,
        case_id: UUID,
        title: str | None = None,
        description: str | None = None,
        editor_user_id: UUID,
        now: datetime | None = None,
        service: str,
        instance_id: str,
        trace_id: str | None = None,
        span_id: str | None = None,
    ) -> CaseRow:
        at = now or datetime.now(tz=UTC)
        changed: dict[str, Any] = {}
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            table = await _require_case(session, case_id)
            if table.status is CaseStatus.ARCHIVED:
                raise CaseError("archived cases cannot be updated")
            if title is not None and title != table.title:
                if len(title) < _MIN_TITLE_LEN:
                    raise CaseError("title must be at least 3 characters")
                changed["title"] = {"from": table.title, "to": title}
                table.title = title
            if description is not None and description != table.description:
                changed["description"] = {"from": table.description, "to": description}
                table.description = description
            if not changed:
                return _case_row(table)
            session.add(table)
            await session.commit()
            await session.refresh(table)
            row = _case_row(table)
        await self._emit_case_audit(
            event=AuditSubject.CASE_UPDATED,
            actor=editor_user_id,
            subject_id=case_id,
            payload={"changes": changed},
            at=at,
            service=service,
            instance_id=instance_id,
            trace_id=trace_id,
            span_id=span_id,
        )
        return row

    async def close_case(
        self,
        *,
        case_id: UUID,
        closer_user_id: UUID,
        reason: str,
        now: datetime | None = None,
        service: str,
        instance_id: str,
        trace_id: str | None = None,
        span_id: str | None = None,
    ) -> CaseRow:
        if len(reason) < _MIN_REASON_LEN:
            raise CaseError("close reason must be at least 16 characters")
        at = now or datetime.now(tz=UTC)
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            table = await _require_case(session, case_id)
            if table.status is not CaseStatus.OPEN:
                raise CaseError(f"cannot close case in status {table.status.value}")
            table.status = CaseStatus.CLOSED
            table.closed_at = at
            table.closed_by_user_id = closer_user_id
            table.close_reason = reason
            session.add(table)
            await session.commit()
            await session.refresh(table)
            row = _case_row(table)
        await self._emit_case_audit(
            event=AuditSubject.CASE_CLOSED,
            actor=closer_user_id,
            subject_id=case_id,
            payload={"reason": reason},
            at=at,
            service=service,
            instance_id=instance_id,
            trace_id=trace_id,
            span_id=span_id,
        )
        return row

    async def reopen_case(
        self,
        *,
        case_id: UUID,
        reopener_user_id: UUID,
        now: datetime | None = None,
        service: str,
        instance_id: str,
        trace_id: str | None = None,
        span_id: str | None = None,
    ) -> CaseRow:
        at = now or datetime.now(tz=UTC)
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            table = await _require_case(session, case_id)
            if table.status is not CaseStatus.CLOSED:
                raise CaseError(f"only CLOSED cases can be reopened (got {table.status.value})")
            table.status = CaseStatus.OPEN
            table.closed_at = None
            table.closed_by_user_id = None
            table.close_reason = None
            session.add(table)
            await session.commit()
            await session.refresh(table)
            row = _case_row(table)
        await self._emit_case_audit(
            event=AuditSubject.CASE_REOPENED,
            actor=reopener_user_id,
            subject_id=case_id,
            payload={},
            at=at,
            service=service,
            instance_id=instance_id,
            trace_id=trace_id,
            span_id=span_id,
        )
        return row

    async def archive_case(
        self,
        *,
        case_id: UUID,
        archiver_user_id: UUID,
        reason: str,
        now: datetime | None = None,
        service: str,
        instance_id: str,
        trace_id: str | None = None,
        span_id: str | None = None,
    ) -> CaseRow:
        if len(reason) < _MIN_REASON_LEN:
            raise CaseError("archive reason must be at least 16 characters")
        at = now or datetime.now(tz=UTC)
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            table = await _require_case(session, case_id)
            if table.status is not CaseStatus.CLOSED:
                raise CaseError(f"only CLOSED cases can be archived (got {table.status.value})")
            table.status = CaseStatus.ARCHIVED
            table.archived_at = at
            table.archived_by_user_id = archiver_user_id
            table.archive_reason = reason
            session.add(table)
            await session.commit()
            await session.refresh(table)
            row = _case_row(table)
        await self._emit_case_audit(
            event=AuditSubject.CASE_ARCHIVED,
            actor=archiver_user_id,
            subject_id=case_id,
            payload={"reason": reason},
            at=at,
            service=service,
            instance_id=instance_id,
            trace_id=trace_id,
            span_id=span_id,
        )
        return row

    async def update_case_discovery_policy(
        self,
        *,
        case_id: UUID,
        seed_root_group_ids: list[UUID] | None = None,
        redundancy_policy: RedundancyPolicy | None = None,
        auto_join_policy: AutoJoinPolicy | None = None,
        auto_join_score_threshold: float | None = None,
        clear_score_threshold: bool = False,
        editor_user_id: UUID,
        now: datetime | None = None,
        service: str,
        instance_id: str,
        trace_id: str | None = None,
        span_id: str | None = None,
    ) -> CaseRow:
        """Set the discovery-loop policy fields on a Case (API_PLAN §4.12 / M9.D4).

        Each policy argument is optional; ``None`` leaves the field unchanged.
        ``auto_join_score_threshold=None`` is therefore *leave unchanged* — pass
        ``clear_score_threshold=True`` to explicitly null it.

        Changing ``seed_root_group_ids`` emits ``case.seed_roots_changed`` (the
        reachable-root dimension of the §4.12.3 eligibility predicate shifts);
        the prior + new lists are frozen in the audit payload. Archived cases
        refuse the mutation.
        """
        at = now or datetime.now(tz=UTC)
        seed_roots_changed = False
        prior_roots: list[str] = []
        new_roots: list[str] = []
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            table = await _require_case(session, case_id)
            if table.status is CaseStatus.ARCHIVED:
                raise CaseError("archived cases cannot be updated")
            if seed_root_group_ids is not None:
                prior_roots = list(table.seed_root_group_ids)
                new_roots = [str(g) for g in seed_root_group_ids]
                if new_roots != prior_roots:
                    seed_roots_changed = True
                    table.seed_root_group_ids = new_roots
            if redundancy_policy is not None:
                table.redundancy_policy = redundancy_policy
            if auto_join_policy is not None:
                table.auto_join_policy = auto_join_policy
            if clear_score_threshold:
                table.auto_join_score_threshold = None
            elif auto_join_score_threshold is not None:
                table.auto_join_score_threshold = auto_join_score_threshold
            session.add(table)
            await session.commit()
            await session.refresh(table)
            row = _case_row(table)
        if seed_roots_changed:
            await self._emit_case_audit(
                event=AuditSubject.CASE_SEED_ROOTS_CHANGED,
                actor=editor_user_id,
                subject_id=case_id,
                payload={"from": prior_roots, "to": new_roots},
                at=at,
                service=service,
                instance_id=instance_id,
                trace_id=trace_id,
                span_id=span_id,
            )
        return row

    # -- reads -----------------------------------------------------------------

    async def get_case(self, case_id: UUID) -> CaseRow | None:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            table = await session.get(CaseTable, case_id)
            return _case_row(table) if table is not None else None

    async def resolve_case_for_candidate(self, candidate_id: UUID) -> CaseRow | None:
        """Return the Case whose seed roots reach a candidate (API_PLAN §4.12.3).

        A candidate is in scope for a Case when any of its mentions'
        ``seed_root_id`` appears in that Case's ``seed_root_group_ids``. If
        several Cases match (overlapping seed sets — an operator-created
        ambiguity), the oldest by ``created_at`` wins deterministically.
        Returns ``None`` when no Case claims the candidate's seed roots (the
        eligibility predicate then has no redundancy policy to apply).
        """
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            mention_stmt = select(GroupCandidateMentionTable.seed_root_id).where(
                col(GroupCandidateMentionTable.candidate_id) == candidate_id,
                col(GroupCandidateMentionTable.seed_root_id).is_not(None),
            )
            mention_result = await session.exec(mention_stmt)
            seed_roots = {str(r) for r in mention_result if r is not None}
            if not seed_roots:
                return None

            case_stmt = select(CaseTable).order_by(col(CaseTable.created_at).asc())
            case_result = await session.exec(case_stmt)
            for table in case_result:
                if seed_roots.intersection(table.seed_root_group_ids):
                    return _case_row(table)
            return None

    async def list_case_members(self, case_id: UUID) -> list[CaseMemberRow]:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = select(CaseMemberTable).where(
                col(CaseMemberTable.case_id) == case_id,
                col(CaseMemberTable.removed_at).is_(None),
            )
            result = await session.exec(stmt)
            return [_member_row(r) for r in list(result)]

    async def list_case_collaborators(self, case_id: UUID) -> list[CaseCollaboratorRow]:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = select(CaseCollaboratorTable).where(
                col(CaseCollaboratorTable.case_id) == case_id,
                col(CaseCollaboratorTable.revoked_at).is_(None),
            )
            result = await session.exec(stmt)
            return [_collab_row(r) for r in list(result)]

    # -- members ---------------------------------------------------------------

    async def add_case_member(
        self,
        *,
        case_id: UUID,
        subject_kind: CaseSubjectKind,
        subject_id: UUID,
        added_by_user_id: UUID,
        reason: str,
        now: datetime | None = None,
        service: str,
        instance_id: str,
        trace_id: str | None = None,
        span_id: str | None = None,
    ) -> CaseMemberRow:
        if len(reason) < _MIN_REASON_LEN:
            raise CaseError("add_reason must be at least 16 characters")
        at = now or datetime.now(tz=UTC)
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            case = await _require_case(session, case_id)
            if case.status is CaseStatus.ARCHIVED:
                raise CaseError("cannot add members to an archived case")
            stmt = select(CaseMemberTable).where(
                col(CaseMemberTable.case_id) == case_id,
                col(CaseMemberTable.subject_kind) == subject_kind,
                col(CaseMemberTable.subject_id) == subject_id,
                col(CaseMemberTable.removed_at).is_(None),
            )
            existing_result = await session.exec(stmt)
            if existing_result.first() is not None:
                raise CaseError(f"{subject_kind.value}:{subject_id} is already an active member")
            table = CaseMemberTable(
                case_id=case_id,
                subject_kind=subject_kind,
                subject_id=subject_id,
                added_by_user_id=added_by_user_id,
                added_at=at,
                add_reason=reason,
            )
            session.add(table)
            await session.commit()
            await session.refresh(table)
            row = _member_row(table)
        await self._emit_case_audit(
            event=AuditSubject.CASE_MEMBER_ADDED,
            actor=added_by_user_id,
            subject_id=case_id,
            payload={
                "member_id": str(row.id),
                "subject_kind": subject_kind.value,
                "subject_id": str(subject_id),
                "reason": reason,
            },
            at=at,
            service=service,
            instance_id=instance_id,
            trace_id=trace_id,
            span_id=span_id,
        )
        await self._maybe_emit_tier_change(
            case_id=case_id,
            actor=added_by_user_id,
            at=at,
            service=service,
            instance_id=instance_id,
            trace_id=trace_id,
            span_id=span_id,
        )
        return row

    async def remove_case_member(
        self,
        *,
        member_id: UUID,
        remover_user_id: UUID,
        reason: str,
        now: datetime | None = None,
        service: str,
        instance_id: str,
        trace_id: str | None = None,
        span_id: str | None = None,
    ) -> CaseMemberRow:
        if len(reason) < _MIN_REASON_LEN:
            raise CaseError("removal reason must be at least 16 characters")
        at = now or datetime.now(tz=UTC)
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            table = await session.get(CaseMemberTable, member_id)
            if table is None:
                raise CaseError(f"member {member_id} not found")
            if table.removed_at is not None:
                raise CaseError(f"member {member_id} already removed")
            case_id = table.case_id
            table.removed_at = at
            table.removed_by_user_id = remover_user_id
            table.removal_reason = reason
            session.add(table)
            await session.commit()
            await session.refresh(table)
            row = _member_row(table)
        await self._emit_case_audit(
            event=AuditSubject.CASE_MEMBER_REMOVED,
            actor=remover_user_id,
            subject_id=case_id,
            payload={
                "member_id": str(row.id),
                "subject_kind": row.subject_kind.value,
                "subject_id": str(row.subject_id),
                "reason": reason,
            },
            at=at,
            service=service,
            instance_id=instance_id,
            trace_id=trace_id,
            span_id=span_id,
        )
        await self._maybe_emit_tier_change(
            case_id=case_id,
            actor=remover_user_id,
            at=at,
            service=service,
            instance_id=instance_id,
            trace_id=trace_id,
            span_id=span_id,
        )
        return row

    # -- collaborators ---------------------------------------------------------

    async def add_case_collaborator(
        self,
        *,
        case_id: UUID,
        user_id: UUID,
        role: CaseRoleOnCase,
        granted_by_user_id: UUID,
        now: datetime | None = None,
        service: str,
        instance_id: str,
        trace_id: str | None = None,
        span_id: str | None = None,
    ) -> CaseCollaboratorRow:
        at = now or datetime.now(tz=UTC)
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            case = await _require_case(session, case_id)
            if case.status is CaseStatus.ARCHIVED:
                raise CaseError("cannot add collaborators to an archived case")
            stmt = select(CaseCollaboratorTable).where(
                col(CaseCollaboratorTable.case_id) == case_id,
                col(CaseCollaboratorTable.user_id) == user_id,
                col(CaseCollaboratorTable.revoked_at).is_(None),
            )
            existing_result = await session.exec(stmt)
            if existing_result.first() is not None:
                raise CaseError(f"user {user_id} is already an active collaborator")
            table = CaseCollaboratorTable(
                case_id=case_id,
                user_id=user_id,
                role_on_case=role,
                granted_by_user_id=granted_by_user_id,
                granted_at=at,
            )
            session.add(table)
            await session.commit()
            await session.refresh(table)
            row = _collab_row(table)
        await self._emit_case_audit(
            event=AuditSubject.CASE_COLLABORATOR_ADDED,
            actor=granted_by_user_id,
            subject_id=case_id,
            payload={
                "collaborator_id": str(row.id),
                "user_id": str(user_id),
                "role": role.value,
            },
            at=at,
            service=service,
            instance_id=instance_id,
            trace_id=trace_id,
            span_id=span_id,
        )
        return row

    async def revoke_case_collaborator(
        self,
        *,
        collaborator_id: UUID,
        revoker_user_id: UUID,
        reason: str,
        now: datetime | None = None,
        service: str,
        instance_id: str,
        trace_id: str | None = None,
        span_id: str | None = None,
    ) -> CaseCollaboratorRow:
        if len(reason) < _MIN_REASON_LEN:
            raise CaseError("revocation reason must be at least 16 characters")
        at = now or datetime.now(tz=UTC)
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            table = await session.get(CaseCollaboratorTable, collaborator_id)
            if table is None:
                raise CaseError(f"collaborator {collaborator_id} not found")
            if table.revoked_at is not None:
                raise CaseError(f"collaborator {collaborator_id} already revoked")
            table.revoked_at = at
            table.revoked_by_user_id = revoker_user_id
            table.revocation_reason = reason
            session.add(table)
            await session.commit()
            await session.refresh(table)
            row = _collab_row(table)
        await self._emit_case_audit(
            event=AuditSubject.CASE_COLLABORATOR_REVOKED,
            actor=revoker_user_id,
            subject_id=row.case_id,
            payload={
                "collaborator_id": str(row.id),
                "user_id": str(row.user_id),
                "reason": reason,
            },
            at=at,
            service=service,
            instance_id=instance_id,
            trace_id=trace_id,
            span_id=span_id,
        )
        return row

    # -- access denied ---------------------------------------------------------

    async def emit_case_access_denied(
        self,
        *,
        case_id: UUID,
        user_id: UUID,
        reason: str,
        now: datetime | None = None,
        service: str,
        instance_id: str,
        trace_id: str | None = None,
        span_id: str | None = None,
    ) -> None:
        at = now or datetime.now(tz=UTC)
        await self._emit_case_audit(
            event=AuditSubject.CASE_ACCESS_DENIED,
            actor=user_id,
            subject_id=case_id,
            payload={"reason": reason},
            at=at,
            service=service,
            instance_id=instance_id,
            trace_id=trace_id,
            span_id=span_id,
        )

    # -- effective tier --------------------------------------------------------

    async def _recompute_effective_tier(
        self, session: AsyncSession, case_id: UUID
    ) -> SensitivityTier:
        stmt = select(CaseMemberTable).where(
            col(CaseMemberTable.case_id) == case_id,
            col(CaseMemberTable.removed_at).is_(None),
        )
        result = await session.exec(stmt)
        max_rank = 0
        for member in list(result):
            if member.subject_kind is CaseSubjectKind.OBSERVATION:
                obs = await session.get(ObservationTable, member.subject_id)
                if obs is not None:
                    eff = obs.operator_tier_override or obs.classifier_tier
                    max_rank = max(max_rank, TIER_RANK[eff])
            elif member.subject_kind is CaseSubjectKind.ATTACHMENT:
                att = await session.get(AttachmentTable, member.subject_id)
                if att is not None:
                    eff = att.operator_tier_override or att.classifier_tier
                    max_rank = max(max_rank, TIER_RANK[eff])
        return RANK_TIER[max_rank]

    async def _maybe_emit_tier_change(
        self,
        *,
        case_id: UUID,
        actor: UUID,
        at: datetime,
        service: str,
        instance_id: str,
        trace_id: str | None,
        span_id: str | None,
    ) -> None:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            table = await session.get(CaseTable, case_id)
            if table is None:
                return
            new_tier = await self._recompute_effective_tier(session, case_id)
            if new_tier is table.effective_tier:
                return
            old_tier = table.effective_tier
            table.effective_tier = new_tier
            session.add(table)
            await session.commit()
        await self._emit_case_audit(
            event=AuditSubject.CASE_TIER_CHANGED,
            actor=actor,
            subject_id=case_id,
            payload={"from": old_tier.value, "to": new_tier.value},
            at=at,
            service=service,
            instance_id=instance_id,
            trace_id=trace_id,
            span_id=span_id,
        )

    async def _emit_case_audit(
        self,
        *,
        event: AuditSubject,
        actor: UUID | None,
        subject_id: UUID | None,
        payload: dict[str, Any],
        at: datetime,
        service: str,
        instance_id: str,
        trace_id: str | None,
        span_id: str | None,
    ) -> None:
        await audit_or_warn(
            self,  # type: ignore[arg-type]
            build_audit_row(
                event=event,
                actor=actor,
                subject_kind=_CASE_SUBJECT_KIND,
                subject_id=subject_id,
                payload=payload,
                at=at,
                service=service,
                instance_id=instance_id,
                trace_id=trace_id,
                span_id=span_id,
            ),
            helper=f"cases.{event.name.lower()}",
            domain_id=subject_id,
        )


__all__ = ["CasesMixin"]
