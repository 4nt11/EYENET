# SPDX-License-Identifier: AGPL-3.0-or-later
"""SourcesMixin — SourceDomain CRUD with in-transaction overlap detection.

Mixin is ANSI SQL only (CLAUDE.md §2.3 Rule 1): no dialect-specific
imports, no ``ON CONFLICT``, no ``BEGIN IMMEDIATE``. Overlap detection
runs as a SELECT + pure-Python intersection check + INSERT inside one
:func:`safe_session` transaction. SQLite's single-writer lock serializes
concurrent writers correctly; for the future Postgres backend, this
section needs a ``SELECT ... FOR UPDATE`` over the relevant rows or a
per-source advisory lock — see the TODO inside
:meth:`SourcesMixin._detect_overlap_in_session`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy import func
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from eyenet.contracts.enums import ResolutionState, SourceDomainPatternKind
from eyenet.contracts.source import SourceBridgeSummary, SourceRow
from eyenet.contracts.source_domain import SourceDomainRow
from eyenet.models.infrastructure import InfrastructureArtifactTable
from eyenet.models.source import SourceTable
from eyenet.models.source_domain import SourceDomainTable
from eyenet.storage.errors import SourceCanonicalUrlError, SourceDomainOverlapError
from eyenet.util.domain import normalize_host, pattern_matches_host, patterns_intersect

from ._helpers import safe_session


def _coerce_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _row(table: SourceDomainTable) -> SourceDomainRow:
    # exclude the generated column from the dump — Pydantic emits a
    # UserWarning when SQLite hands back a TEXT value for a UUID-typed
    # field, and the contract layer doesn't carry the column anyway.
    data = table.model_dump(exclude={"active_primary_source_id"})
    for k in ("created_at", "removed_at"):
        data[k] = _coerce_utc(data.get(k))
    return SourceDomainRow.model_validate(data)


def _source_row(table: SourceTable) -> SourceRow:
    data = table.model_dump()
    data["created_at"] = _coerce_utc(data.get("created_at"))
    return SourceRow.model_validate(data)


# Lookup order for find_source_for_host. Lower index = higher specificity.
_KIND_SPECIFICITY: tuple[SourceDomainPatternKind, ...] = (
    SourceDomainPatternKind.EXACT,
    SourceDomainPatternKind.SUBDOMAIN_WILDCARD,
    SourceDomainPatternKind.SUFFIX_MATCH,
)


class SourcesMixin:
    """SourceDomain CRUD + overlap detection."""

    # ---- M9.D1 read surface (Group C left only get/upsert + domain writes) ----

    async def list_sources(
        self,
        *,
        limit: int,
        offset: int = 0,
    ) -> list[SourceRow]:
        """Return Sources ordered ``created_at ASC``, paginated."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = (
                select(SourceTable)
                .order_by(col(SourceTable.created_at).asc())
                .offset(offset)
                .limit(limit)
            )
            result = await session.exec(stmt)
            return [_source_row(r) for r in list(result)]

    async def count_sources(self) -> int:
        """Total Source rows."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = select(func.count()).select_from(SourceTable)
            result = await session.exec(stmt)
            return int(result.one())

    async def list_source_domains(
        self,
        *,
        source_id: UUID,
        include_removed: bool = False,
    ) -> list[SourceDomainRow]:
        """Return SourceDomain rows for ``source_id``.

        Active rows only by default; ``include_removed=True`` returns the
        soft-deleted rows too (audit view). Order: ``created_at ASC``.
        """
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = select(SourceDomainTable).where(
                col(SourceDomainTable.source_id) == source_id,
            )
            if not include_removed:
                stmt = stmt.where(col(SourceDomainTable.removed_at).is_(None))
            stmt = stmt.order_by(col(SourceDomainTable.created_at).asc())
            result = await session.exec(stmt)
            return [_row(r) for r in list(result)]

    async def swap_source_domain_primary(
        self,
        *,
        source_id: UUID,
        domain_id: UUID,
    ) -> SourceDomainRow:
        """Make ``domain_id`` the active primary domain for ``source_id``.

        Clears ``is_primary`` on any other active primary for the source and
        sets it on the target — in one transaction, so the partial-unique
        ``uq_source_domain_one_primary`` never sees two primaries. The
        target must belong to ``source_id`` and not be soft-removed.

        Raises :class:`ValueError` if the target is missing, removed, or
        belongs to a different Source.
        """
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            target = await session.get(SourceDomainTable, domain_id)
            if target is None or target.source_id != source_id:
                raise ValueError(f"source_domain {domain_id} not found for source {source_id}")
            if target.removed_at is not None:
                raise ValueError(f"source_domain {domain_id} is removed; cannot be primary")
            # Demote the current active primary (if any, and not the target).
            current = select(SourceDomainTable).where(
                col(SourceDomainTable.source_id) == source_id,
                col(SourceDomainTable.is_primary).is_(True),
                col(SourceDomainTable.removed_at).is_(None),
            )
            for row in list(await session.exec(current)):
                if row.id != domain_id:
                    row.is_primary = False
                    session.add(row)
            await session.flush()  # demote before promote → unique never doubles
            target.is_primary = True
            session.add(target)
            await session.commit()
            await session.refresh(target)
            return _row(target)

    async def source_bridge_summary(self, *, source_id: UUID) -> SourceBridgeSummary:
        """Bridge-resolution counts for a Source (API_PLAN §3.8).

        ``resolved`` is per-source (``resolved_to_source_id == source_id``);
        the other buckets are system-wide outstanding-work context. See
        :class:`SourceBridgeSummary` for the semantics rationale.
        """
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            resolved_stmt = (
                select(func.count())
                .select_from(InfrastructureArtifactTable)
                .where(col(InfrastructureArtifactTable.resolved_to_source_id) == source_id)
            )
            resolved = int((await session.exec(resolved_stmt)).one())

            async def _count_state(state: ResolutionState) -> int:
                stmt = (
                    select(func.count())
                    .select_from(InfrastructureArtifactTable)
                    .where(col(InfrastructureArtifactTable.resolution_state) == state)
                )
                return int((await session.exec(stmt)).one())

            return SourceBridgeSummary(
                source_id=source_id,
                resolved=resolved,
                unresolved=await _count_state(ResolutionState.UNRESOLVED),
                ambiguous=await _count_state(ResolutionState.AMBIGUOUS),
                not_applicable=await _count_state(ResolutionState.NOT_APPLICABLE),
            )

    async def add_source_domain(
        self,
        *,
        source_id: UUID,
        pattern: str,
        pattern_kind: SourceDomainPatternKind,
        is_primary: bool,
        created_at: datetime,
        created_by_user_id: UUID | None = None,
        notes: str | None = None,
    ) -> SourceDomainRow:
        pattern_norm = normalize_host(pattern)
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            await self._detect_overlap_in_session(
                session,
                pattern=pattern_norm,
                pattern_kind=pattern_kind,
            )
            table = SourceDomainTable(
                source_id=source_id,
                pattern=pattern_norm,
                pattern_kind=pattern_kind,
                is_primary=is_primary,
                created_at=created_at,
                created_by_user_id=created_by_user_id,
                notes=notes,
            )
            session.add(table)
            await session.flush()
            # §2.25 Path B: retroactively resolve prior UNRESOLVED bridgeable
            # artifacts whose host matches the just-added pattern. Runs inside
            # this transaction so the SourceDomain insert + artifact updates
            # commit atomically.
            await self._resolve_existing_artifacts_for_new_domain_in_session(  # type: ignore[attr-defined]
                session,
                new_pattern=pattern_norm,
                new_pattern_kind=pattern_kind,
                new_source_id=source_id,
            )
            await session.commit()
            await session.refresh(table)
            return _row(table)

    async def remove_source_domain(
        self,
        *,
        domain_id: UUID,
        removed_at: datetime,
        removed_by_user_id: UUID,
    ) -> SourceDomainRow:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            table = await session.get(SourceDomainTable, domain_id)
            if table is None:
                raise ValueError(f"source_domain {domain_id} not found")
            if table.removed_at is not None:
                raise ValueError(f"source_domain {domain_id} already removed")
            table.removed_at = removed_at
            table.removed_by_user_id = removed_by_user_id
            session.add(table)
            await session.commit()
            await session.refresh(table)
            return _row(table)

    async def find_source_for_host(self, host: str) -> SourceDomainRow | None:
        host_norm = normalize_host(host)
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = select(SourceDomainTable).where(
                col(SourceDomainTable.removed_at).is_(None),
            )
            result = await session.exec(stmt)
            candidates = [
                r
                for r in list(result)
                if pattern_matches_host(r.pattern, r.pattern_kind, host_norm)
            ]
            if not candidates:
                return None
            candidates.sort(
                key=lambda r: (
                    _KIND_SPECIFICITY.index(r.pattern_kind),
                    _coerce_utc(r.created_at) or r.created_at,
                ),
            )
            return _row(candidates[0])

    async def set_source_canonical_url(
        self,
        *,
        source_id: UUID,
        canonical_url: str | None,
    ) -> SourceRow:
        if canonical_url is None:
            return await self._update_source_canonical_url(source_id, None)
        # Parse + validate URL host BEFORE acquiring a session — keeps the
        # validation cost off the connection pool.
        host_norm = _validate_url_host(canonical_url, source_id=source_id)
        primary = await self._active_primary_domain_for(source_id)
        if primary is None:
            raise SourceCanonicalUrlError(
                "no_primary_domain",
                source_id=source_id,
                detail="source has no active primary SourceDomain",
            )
        if not pattern_matches_host(primary.pattern, primary.pattern_kind, host_norm):
            raise SourceCanonicalUrlError(
                "host_not_owned",
                source_id=source_id,
                detail=(
                    f"host {host_norm!r} does not match primary domain "
                    f"({primary.pattern_kind.value} {primary.pattern!r})"
                ),
            )
        return await self._update_source_canonical_url(source_id, canonical_url)

    async def _active_primary_domain_for(
        self,
        source_id: UUID,
    ) -> SourceDomainTable | None:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = select(SourceDomainTable).where(
                col(SourceDomainTable.source_id) == source_id,
                col(SourceDomainTable.is_primary).is_(True),
                col(SourceDomainTable.removed_at).is_(None),
            )
            result = await session.exec(stmt)
            return result.first()

    async def _update_source_canonical_url(
        self,
        source_id: UUID,
        canonical_url: str | None,
    ) -> SourceRow:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            table = await session.get(SourceTable, source_id)
            if table is None:
                raise SourceCanonicalUrlError(
                    "source_not_found",
                    source_id=source_id,
                )
            table.canonical_url = canonical_url
            session.add(table)
            await session.commit()
            await session.refresh(table)
            return _source_row(table)

    async def _detect_overlap_in_session(
        self,
        session: AsyncSession,
        *,
        pattern: str,
        pattern_kind: SourceDomainPatternKind,
    ) -> None:
        """Raise SourceDomainOverlapError if any non-removed row overlaps.

        TODO(postgres): when the Postgres backend lands, this read must
        run with ``SELECT ... FOR UPDATE`` over the candidate row set so
        two concurrent writers serialize. SQLite's RESERVED lock already
        provides this for the SQLite backend; do not add the FOR UPDATE
        hint here — overriding ``add_source_domain`` on the Postgres
        backend is the correct cut.
        """
        stmt = select(SourceDomainTable).where(
            col(SourceDomainTable.removed_at).is_(None),
        )
        result = await session.exec(stmt)
        for row in list(result):
            if patterns_intersect(
                pattern,
                pattern_kind,
                row.pattern,
                row.pattern_kind,
            ):
                raise SourceDomainOverlapError(
                    conflicting_id=row.id,
                    conflict_kind=row.pattern_kind.value,
                )


def _validate_url_host(url: str, *, source_id: UUID) -> str:
    """Extract + normalize the host portion of ``url``.

    Raises :exc:`SourceCanonicalUrlError(reason='invalid_url')` if the
    value lacks a host or the host fails IDN/punycode normalization.
    """
    try:
        parsed = urlparse(url)
    except (TypeError, ValueError) as exc:
        raise SourceCanonicalUrlError(
            "invalid_url",
            source_id=source_id,
            detail=f"unparseable URL: {exc}",
        ) from exc
    if not parsed.hostname:
        raise SourceCanonicalUrlError(
            "invalid_url",
            source_id=source_id,
            detail="URL has no host component",
        )
    try:
        return normalize_host(parsed.hostname)
    except ValueError as exc:
        raise SourceCanonicalUrlError(
            "invalid_url",
            source_id=source_id,
            detail=str(exc),
        ) from exc


__all__ = ["SourcesMixin"]
