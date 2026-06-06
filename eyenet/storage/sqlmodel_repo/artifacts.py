# SPDX-License-Identifier: AGPL-3.0-or-later
"""ArtifactsMixin — InfrastructureArtifact + GroupAccessArtifact + bridge resolution (M9.C6).

Implements the §2.25 bridge-resolution invariant inline. Path A (artifact
write) and Path B (SourceDomain write) both fire inside the same transaction
that creates the asymmetry. No async job, no operator tool.

Because C1's overlap detection guarantees that no two SourceDomain patterns
can both match the same host, the resolution lookup is unambiguous in
practice: at most one Source matches any given host at any time.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlmodel import col, select

from eyenet.contracts.access_artifact import GroupAccessArtifactRow
from eyenet.contracts.enums import (
    ArtifactSubjectKind,
    ArtifactValidationState,
    GroupAccessKind,
    InfrastructureKind,
    ResolutionState,
    SourceDomainPatternKind,
)
from eyenet.contracts.infrastructure import InfrastructureArtifactRow
from eyenet.models.access_artifact import GroupAccessArtifactTable
from eyenet.models.infrastructure import InfrastructureArtifactTable
from eyenet.models.source_domain import SourceDomainTable
from eyenet.util.domain import (
    BRIDGEABLE_KINDS,
    artifact_value_to_host,
    pattern_matches_host,
)

from ._helpers import safe_session

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession


def _coerce_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _artifact_row(table: InfrastructureArtifactTable) -> InfrastructureArtifactRow:
    data = table.model_dump()
    for k in ("first_seen_at_ingest", "last_seen_at_ingest"):
        data[k] = _coerce_utc(data.get(k))
    return InfrastructureArtifactRow.model_validate(data)


def _access_row(table: GroupAccessArtifactTable) -> GroupAccessArtifactRow:
    data = table.model_dump()
    for k in ("discovered_at_ingest", "last_validated_at", "expires_at"):
        data[k] = _coerce_utc(data.get(k))
    return GroupAccessArtifactRow.model_validate(data)


def _value_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


async def _resolve_artifact_in_session(
    session: AsyncSession,
    *,
    kind: InfrastructureKind,
    value: str,
) -> tuple[ResolutionState, UUID | None]:
    """Compute (resolution_state, resolved_to_source_id) for an artifact.

    Pure DB-read; no writes. Uses the same session so the lookup is
    consistent with whatever SourceDomain rows are visible in the
    transaction. Per §2.25, C1's overlap detection guarantees at most one
    Source matches; AMBIGUOUS is defensive completeness only.
    """
    if kind not in BRIDGEABLE_KINDS:
        return ResolutionState.NOT_APPLICABLE, None
    host = artifact_value_to_host(kind, value)
    if host is None:
        # Malformed value — treat as unresolved rather than crashing the
        # ingest path.
        return ResolutionState.UNRESOLVED, None

    stmt = select(SourceDomainTable).where(col(SourceDomainTable.removed_at).is_(None))
    result = await session.exec(stmt)
    matches = [r for r in list(result) if pattern_matches_host(r.pattern, r.pattern_kind, host)]
    if not matches:
        return ResolutionState.UNRESOLVED, None
    distinct_sources = {r.source_id for r in matches}
    if len(distinct_sources) == 1:
        return ResolutionState.RESOLVED, matches[0].source_id
    return ResolutionState.AMBIGUOUS, None


class ArtifactsMixin:
    """Infrastructure + access artifact CRUD with inline bridge resolution."""

    async def put_infrastructure_artifact(
        self,
        *,
        kind: InfrastructureKind,
        value: str,
        first_seen_at_ingest: datetime,
        last_seen_at_ingest: datetime,
    ) -> InfrastructureArtifactRow:
        """Insert (or update last_seen on) an InfrastructureArtifact.

        Path A: resolution against existing SourceDomain rows runs inline,
        in the same transaction as the write. ``resolved_to_source_id`` and
        ``resolution_state`` are populated before COMMIT.

        Idempotent on ``value_hash`` — calling twice for the same value
        updates ``last_seen_at_ingest`` and re-runs resolution (so a
        previously-unresolved artifact picks up a Source that was created
        in between).
        """
        v_hash = _value_hash(value)
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            existing_stmt = select(InfrastructureArtifactTable).where(
                InfrastructureArtifactTable.value_hash == v_hash,
            )
            existing_result = await session.exec(existing_stmt)
            existing = existing_result.one_or_none()

            state, resolved_to = await _resolve_artifact_in_session(
                session,
                kind=kind,
                value=value,
            )

            if existing is not None:
                existing.last_seen_at_ingest = last_seen_at_ingest
                existing.resolution_state = state
                existing.resolved_to_source_id = resolved_to
                session.add(existing)
                await session.commit()
                await session.refresh(existing)
                return _artifact_row(existing)

            row = InfrastructureArtifactTable(
                kind=kind,
                value=value,
                value_hash=v_hash,
                first_seen_at_ingest=first_seen_at_ingest,
                last_seen_at_ingest=last_seen_at_ingest,
                resolution_state=state,
                resolved_to_source_id=resolved_to,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return _artifact_row(row)

    async def get_infrastructure_artifact(
        self,
        artifact_id: UUID,
    ) -> InfrastructureArtifactRow | None:
        """Return one InfrastructureArtifactRow by id, or ``None``."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            table = await session.get(InfrastructureArtifactTable, artifact_id)
            return _artifact_row(table) if table is not None else None

    async def list_artifacts_for_source(
        self,
        source_id: UUID,
    ) -> list[InfrastructureArtifactRow]:
        """Return all InfrastructureArtifacts resolved to ``source_id``."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = select(InfrastructureArtifactTable).where(
                InfrastructureArtifactTable.resolved_to_source_id == source_id,
            )
            result = await session.exec(stmt)
            return [_artifact_row(r) for r in list(result)]

    async def add_group_access_artifact(
        self,
        *,
        subject_kind: ArtifactSubjectKind,
        group_id: UUID | None,
        candidate_id: UUID | None,
        kind: GroupAccessKind,
        value: str | None,
        discovered_at_ingest: datetime,
        details: dict[str, Any] | None = None,
        discovered_via_mention_id: UUID | None = None,
        validation_state: ArtifactValidationState | None = None,
        requires_admin_approval: bool = False,
        expires_at: datetime | None = None,
    ) -> GroupAccessArtifactRow:
        """Insert a new GroupAccessArtifact. Caller enforces XOR on (group_id,
        candidate_id); the CHECK constraint is the durable backstop."""
        effective_state = validation_state or ArtifactValidationState.UNVERIFIED
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            row = GroupAccessArtifactTable(
                subject_kind=subject_kind,
                group_id=group_id,
                candidate_id=candidate_id,
                kind=kind,
                value=value,
                details=details or {},
                discovered_via_mention_id=discovered_via_mention_id,
                discovered_at_ingest=discovered_at_ingest,
                validation_state=effective_state,
                requires_admin_approval=requires_admin_approval,
                expires_at=expires_at,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return _access_row(row)

    async def get_group_access_artifact(
        self,
        artifact_id: UUID,
    ) -> GroupAccessArtifactRow | None:
        """Return one GroupAccessArtifactRow by id, or ``None`` (M9.E5.5)."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            table = await session.get(GroupAccessArtifactTable, artifact_id)
            return _access_row(table) if table is not None else None

    async def list_group_access_artifacts_for_candidate(
        self,
        candidate_id: UUID,
    ) -> list[GroupAccessArtifactRow]:
        """Return every GroupAccessArtifact whose subject is ``candidate_id``.

        No SQL-side ordering — the supervisor ranks by ``GroupAccessKind``
        preference (not enum-string order) in Python (M9.E5.5, §4.12.4).
        """
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = select(GroupAccessArtifactTable).where(
                GroupAccessArtifactTable.candidate_id == candidate_id,
            )
            result = await session.exec(stmt)
            return [_access_row(r) for r in list(result)]

    async def set_artifact_validation_state(
        self,
        *,
        artifact_id: UUID,
        validation_state: ArtifactValidationState,
        last_validated_at: datetime,
    ) -> GroupAccessArtifactRow | None:
        """Update a GroupAccessArtifact's validation lifecycle, or ``None`` if
        the row is gone (M9.E5.5).

        A failed invite join writes the dead-link verdict back here
        (``EXPIRED`` / ``REVOKED``) so the supervisor's selection won't
        re-offer it on the next tick.
        """
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            row = await session.get(GroupAccessArtifactTable, artifact_id)
            if row is None:
                return None
            row.validation_state = validation_state
            row.last_validated_at = last_validated_at
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return _access_row(row)

    async def _resolve_existing_artifacts_for_new_domain_in_session(
        self,
        session: AsyncSession,
        *,
        new_pattern: str,
        new_pattern_kind: object,  # SourceDomainPatternKind (avoid circular import)
        new_source_id: UUID,
    ) -> int:
        """Path B sweep — re-evaluate every UNRESOLVED bridgeable artifact
        against the newly-added SourceDomain pattern. Returns the count of
        artifacts that became RESOLVED.

        Runs inside the caller's session (the ``add_source_domain``
        transaction), so the resolution is part of the same atomic commit.

        Because C1's overlap detection guarantees no two patterns both
        match the same host, every artifact that matches the new pattern
        cannot already be resolved to another Source.
        """
        if not isinstance(new_pattern_kind, SourceDomainPatternKind):
            raise TypeError(f"expected SourceDomainPatternKind, got {type(new_pattern_kind)!r}")

        stmt = select(InfrastructureArtifactTable).where(
            InfrastructureArtifactTable.resolution_state == ResolutionState.UNRESOLVED,
        )
        result = await session.exec(stmt)
        resolved_count = 0
        for art in list(result):
            if art.kind not in BRIDGEABLE_KINDS:
                continue
            host = artifact_value_to_host(art.kind, art.value)
            if host is None:
                continue
            if pattern_matches_host(new_pattern, new_pattern_kind, host):
                art.resolution_state = ResolutionState.RESOLVED
                art.resolved_to_source_id = new_source_id
                session.add(art)
                resolved_count += 1
        # Caller commits the outer transaction; we just flush dirty rows.
        return resolved_count


__all__ = ["ArtifactsMixin"]
