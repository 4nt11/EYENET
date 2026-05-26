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
from uuid import UUID

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from eyenet.contracts.enums import SourceDomainPatternKind
from eyenet.contracts.source_domain import SourceDomainRow
from eyenet.models.source_domain import SourceDomainTable
from eyenet.storage.errors import SourceDomainOverlapError
from eyenet.util.domain import normalize_host, patterns_intersect

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


# Lookup order for find_source_for_host. Lower index = higher specificity.
_KIND_SPECIFICITY: tuple[SourceDomainPatternKind, ...] = (
    SourceDomainPatternKind.EXACT,
    SourceDomainPatternKind.SUBDOMAIN_WILDCARD,
    SourceDomainPatternKind.SUFFIX_MATCH,
)


class SourcesMixin:
    """SourceDomain CRUD + overlap detection."""

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
            candidates = [r for r in list(result) if _matches(r, host_norm)]
            if not candidates:
                return None
            candidates.sort(
                key=lambda r: (
                    _KIND_SPECIFICITY.index(r.pattern_kind),
                    _coerce_utc(r.created_at) or r.created_at,
                ),
            )
            return _row(candidates[0])

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


def _matches(row: SourceDomainTable, host: str) -> bool:
    """True iff `row.pattern_kind` matches the normalized `host`."""
    kind = row.pattern_kind
    pattern = row.pattern
    if kind is SourceDomainPatternKind.EXACT:
        return host == pattern
    if kind is SourceDomainPatternKind.SUBDOMAIN_WILDCARD:
        return host.endswith("." + pattern) and host != pattern
    if kind is SourceDomainPatternKind.SUFFIX_MATCH:
        return host == pattern or host.endswith("." + pattern)
    # StrEnum is exhaustive at runtime; unreachable.
    raise AssertionError(f"unhandled pattern kind {kind!r}")


__all__ = ["SourcesMixin"]
