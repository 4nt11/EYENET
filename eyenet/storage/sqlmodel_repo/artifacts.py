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

from sqlalchemy import Select, delete, distinct, func
from sqlmodel import col, select

from eyenet.contracts.access_artifact import GroupAccessArtifactRow
from eyenet.contracts.enums import (
    ArtifactSubjectKind,
    ArtifactValidationState,
    GroupAccessKind,
    ResolutionState,
    SourceDomainPatternKind,
)
from eyenet.contracts.infrastructure import InfrastructureArtifactRow
from eyenet.models.access_artifact import GroupAccessArtifactTable
from eyenet.models.actor import ActorTable
from eyenet.models.group import GroupTable
from eyenet.models.infrastructure import (
    ActorArtifactTable,
    DocumentArtifactTable,
    InfrastructureArtifactMentionTable,
    InfrastructureArtifactTable,
)
from eyenet.models.message import MessageTable
from eyenet.models.source_domain import SourceDomainTable
from eyenet.util.domain import (
    BRIDGEABLE_KINDS,
    artifact_value_to_host,
    pattern_matches_host,
)

from ._helpers import safe_session

if TYPE_CHECKING:
    from collections.abc import Sequence

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


def _apply_artifact_filters[SelectT: Select[Any]](
    stmt: SelectT,
    *,
    kind: str | None,
    q: str | None,
    resolution_state: ResolutionState | None,
) -> SelectT:
    """Apply the shared browse filters to a SELECT over InfrastructureArtifact."""
    a = InfrastructureArtifactTable
    if kind is not None:
        stmt = stmt.where(col(a.kind) == kind)
    if resolution_state is not None:
        stmt = stmt.where(col(a.resolution_state) == resolution_state)
    if q:
        # Case-insensitive substring. Generic lower()+LIKE, NOT Postgres ILIKE, so
        # the mixin stays dialect-free. Artifact values (domains/IPs/wallets/handles)
        # never contain LIKE metachars, so q is used unescaped. ponytail: a pg_trgm
        # index is the postgres-side speedup if this scan ever proves slow.
        stmt = stmt.where(func.lower(col(a.value)).like(f"%{q.lower()}%"))
    return stmt


async def _resolve_artifact_in_session(
    session: AsyncSession,
    *,
    kind: str,
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


def _resolve_against(
    domains: list[SourceDomainTable],
    kind: str,
    value: str,
) -> tuple[ResolutionState, UUID | None]:
    """Pure §2.25 resolution against an already-fetched SourceDomain list — the
    batch form of :func:`_resolve_artifact_in_session` (no per-artifact SELECT)."""
    if kind not in BRIDGEABLE_KINDS:
        return ResolutionState.NOT_APPLICABLE, None
    host = artifact_value_to_host(kind, value)
    if host is None:
        return ResolutionState.UNRESOLVED, None
    matches = [d for d in domains if pattern_matches_host(d.pattern, d.pattern_kind, host)]
    if not matches:
        return ResolutionState.UNRESOLVED, None
    if len({d.source_id for d in matches}) == 1:
        return ResolutionState.RESOLVED, matches[0].source_id
    return ResolutionState.AMBIGUOUS, None


class ArtifactsMixin:
    """Infrastructure + access artifact CRUD with inline bridge resolution."""

    async def put_infrastructure_artifact(
        self,
        *,
        kind: str,
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

    async def delete_infrastructure_artifact(self, artifact_id: UUID) -> bool:
        """Delete one artifact and its dependent rows; True if it existed.

        The schema has no ON DELETE CASCADE, so the dependent FKs are removed
        first (mention edges, then actor_artifact rollup), then the artifact
        row, in one transaction. Graph edges are derived from mentions, so they
        go with them; the ``search_document`` is derived too and is cleaned by
        the caller via :meth:`delete_search_document`. Idempotent: a re-run on a
        missing id deletes nothing and returns False.
        """
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            row = (
                await session.exec(
                    select(InfrastructureArtifactTable).where(
                        col(InfrastructureArtifactTable.id) == artifact_id
                    )
                )
            ).one_or_none()
            if row is None:
                return False
            await session.exec(
                delete(InfrastructureArtifactMentionTable).where(
                    col(InfrastructureArtifactMentionTable.artifact_id) == artifact_id
                )
            )
            await session.exec(
                delete(ActorArtifactTable).where(col(ActorArtifactTable.artifact_id) == artifact_id)
            )
            await session.delete(row)
            await session.commit()
            return True

    async def artifacts_for_revalidation(
        self,
        *,
        kinds: Sequence[str],
        limit: int,
        after_id: UUID | None,
    ) -> list[tuple[UUID, str, str]]:
        """Keyset page of ``(id, kind, value)`` — the lean checksum-sweep scan.

        Aggregate-free (no mention join) and keyset by id (uuid7 is monotonic),
        so a whole-corpus walk is O(n), unlike list_infrastructure_artifacts'
        GROUP BY + OFFSET. Generic ORM; stays in the shared mixin.
        """
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = (
                select(
                    col(InfrastructureArtifactTable.id),
                    col(InfrastructureArtifactTable.kind),
                    col(InfrastructureArtifactTable.value),
                )
                .where(col(InfrastructureArtifactTable.kind).in_(list(kinds)))
                .order_by(col(InfrastructureArtifactTable.id).asc())
                .limit(limit)
            )
            if after_id is not None:
                stmt = stmt.where(col(InfrastructureArtifactTable.id) > after_id)
            result = await session.exec(stmt)
            return [(aid, kind, value) for aid, kind, value in result]

    async def delete_infrastructure_artifacts_bulk(self, artifact_ids: Sequence[UUID]) -> int:
        """Bulk-delete artifacts + dependents in one transaction; rows removed.

        One DELETE per dependent table (mention edges, actor rollup) then the
        artifacts, all keyed by ``id IN (...)``. Empty input is a no-op. The
        caller chunks the id list to keep the IN set bounded.
        """
        ids = list(artifact_ids)
        if not ids:
            return 0
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            await session.exec(
                delete(InfrastructureArtifactMentionTable).where(
                    col(InfrastructureArtifactMentionTable.artifact_id).in_(ids)
                )
            )
            await session.exec(
                delete(ActorArtifactTable).where(col(ActorArtifactTable.artifact_id).in_(ids))
            )
            result = await session.exec(
                delete(InfrastructureArtifactTable).where(
                    col(InfrastructureArtifactTable.id).in_(ids)
                )
            )
            await session.commit()
            return int(result.rowcount or 0)

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

    async def record_artifact_mention(
        self,
        *,
        artifact_id: UUID,
        message_id: UUID,
        char_offset: int | None,
        ts: datetime,
    ) -> bool:
        """Record a per-message provenance edge for an artifact. Idempotent on
        ``(artifact_id, message_id)``: a second call for the same pair is a no-op
        returning ``False``; a new edge returns ``True``."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            existing = await session.exec(
                select(InfrastructureArtifactMentionTable).where(
                    InfrastructureArtifactMentionTable.artifact_id == artifact_id,
                    InfrastructureArtifactMentionTable.message_id == message_id,
                )
            )
            if existing.one_or_none() is not None:
                return False
            session.add(
                InfrastructureArtifactMentionTable(
                    artifact_id=artifact_id,
                    message_id=message_id,
                    char_offset=char_offset,
                    ts=ts,
                )
            )
            await session.commit()
            return True

    async def list_infrastructure_artifacts(
        self,
        *,
        kind: str | None = None,
        q: str | None = None,
        resolution_state: ResolutionState | None = None,
        sort: str = "recent",
        limit: int,
        offset: int,
    ) -> list[tuple[InfrastructureArtifactRow, int, int, int, datetime | None, datetime | None]]:
        """Browse artifacts with read-time mention aggregates (GROUP BY over the
        mention edge joined to message). Generic SQL — no dialect leak."""
        a = InfrastructureArtifactTable
        m = InfrastructureArtifactMentionTable
        msg = MessageTable
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = (
                # sqlmodel's select() typed overloads cap below this arity (model +
                # 5 aggregates); runtime is fine. Same reason list_actors returns
                # type-erased rows.
                select(  # type: ignore[call-overload]
                    a,
                    func.count(distinct(col(m.message_id))),
                    func.count(distinct(col(msg.actor_id))),
                    func.count(distinct(col(msg.group_id))),
                    func.min(col(m.ts)),
                    func.max(col(m.ts)),
                )
                .outerjoin(m, col(m.artifact_id) == col(a.id))
                .outerjoin(msg, col(msg.id) == col(m.message_id))
                .group_by(col(a.id))
            )
            stmt = _apply_artifact_filters(stmt, kind=kind, q=q, resolution_state=resolution_state)
            if sort == "mentions":
                order = [func.count(distinct(col(m.message_id))).desc(), col(a.id)]
            elif sort == "value":
                order = [col(a.value).asc(), col(a.id)]
            elif sort == "first_seen":
                order = [col(a.first_seen_at_ingest).desc(), col(a.id)]
            else:  # recent
                order = [col(a.last_seen_at_ingest).desc(), col(a.id)]
            stmt = stmt.order_by(*order).limit(limit).offset(offset)
            result = await session.exec(stmt)
            return [
                (_artifact_row(art), mentions, actors, groups, _coerce_utc(fts), _coerce_utc(lts))
                for art, mentions, actors, groups, fts, lts in result
            ]

    async def count_infrastructure_artifacts(
        self,
        *,
        kind: str | None = None,
        q: str | None = None,
        resolution_state: ResolutionState | None = None,
    ) -> int:
        """Count artifacts matching the list filters (capped at 10000)."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = _apply_artifact_filters(
                select(func.count()).select_from(InfrastructureArtifactTable),
                kind=kind,
                q=q,
                resolution_state=resolution_state,
            )
            total = (await session.exec(stmt)).one()
            return min(int(total), 10000)

    async def list_artifact_mentions(
        self,
        artifact_id: UUID,
        *,
        limit: int,
        offset: int,
    ) -> list[
        tuple[UUID, UUID, str | None, str | None, UUID, str | None, UUID, datetime, int | None]
    ]:
        """The 'mentioned by' drill-down: one row per sighting, newest first.
        Joins the mention edge to message + actor + group for display."""
        m = InfrastructureArtifactMentionTable
        msg = MessageTable
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = (
                select(  # type: ignore[call-overload]  # 9 columns > sqlmodel select overload arity
                    col(msg.id),
                    col(msg.actor_id),
                    col(ActorTable.current_handle),
                    col(ActorTable.current_display_name),
                    col(msg.group_id),
                    col(GroupTable.current_title),
                    col(msg.source_id),
                    col(m.ts),
                    col(m.char_offset),
                )
                .select_from(m)
                .join(msg, col(msg.id) == col(m.message_id))
                .outerjoin(ActorTable, col(ActorTable.id) == col(msg.actor_id))
                .outerjoin(GroupTable, col(GroupTable.id) == col(msg.group_id))
                .where(col(m.artifact_id) == artifact_id)
                .order_by(col(m.ts).desc(), col(msg.id))
                .limit(limit)
                .offset(offset)
            )
            result = await session.exec(stmt)
            return [
                (mid, aid, ah, adn, gid, gt, sid, _coerce_utc(ts), off)  # type: ignore[misc]
                for mid, aid, ah, adn, gid, gt, sid, ts, off in result
            ]

    async def count_artifact_mentions(self, artifact_id: UUID) -> int:
        """Count mention edges for one artifact (capped at 10000)."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = (
                select(func.count())
                .select_from(InfrastructureArtifactMentionTable)
                .where(col(InfrastructureArtifactMentionTable.artifact_id) == artifact_id)
            )
            return min(int((await session.exec(stmt)).one()), 10000)

    async def put_infrastructure_artifacts_bulk(
        self,
        rows: list[tuple[str, str, datetime, datetime]],
    ) -> dict[str, UUID]:
        """Bulk-upsert artifacts: one SELECT for existing hashes, one SourceDomain
        fetch for batch resolution, one INSERT for the new rows. Returns
        value_hash -> id for every input value."""
        if not rows:
            return {}
        # Dedupe by value_hash; first occurrence wins (times are backfill ingest).
        by_hash: dict[str, tuple[str, str, datetime, datetime]] = {}
        for kind, value, first_seen, last_seen in rows:
            by_hash.setdefault(_value_hash(value), (kind, value, first_seen, last_seen))

        ids: dict[str, UUID] = {}
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            hashes = list(by_hash)
            existing = await session.exec(
                select(InfrastructureArtifactTable).where(
                    col(InfrastructureArtifactTable.value_hash).in_(hashes)
                )
            )
            for art in existing:
                ids[art.value_hash] = art.id

            domains = list(
                await session.exec(
                    select(SourceDomainTable).where(col(SourceDomainTable.removed_at).is_(None))
                )
            )
            fresh: list[tuple[str, UUID]] = []
            for h, (kind, value, first_seen, last_seen) in by_hash.items():
                if h in ids:
                    continue
                state, resolved_to = _resolve_against(domains, kind, value)
                row = InfrastructureArtifactTable(
                    kind=kind,
                    value=value,
                    value_hash=h,
                    first_seen_at_ingest=first_seen,
                    last_seen_at_ingest=last_seen,
                    resolution_state=state,
                    resolved_to_source_id=resolved_to,
                )
                session.add(row)
                fresh.append((h, row.id))  # id is set at construct (uuid7 default)
            await session.commit()
        ids.update(fresh)
        return ids

    async def record_artifact_mentions_bulk(
        self,
        rows: list[tuple[UUID, UUID, int | None, datetime]],
    ) -> int:
        """Bulk-insert mention edges, skipping pairs already stored or duplicated
        within the batch. One SELECT for existing pairs, one INSERT for the rest."""
        if not rows:
            return 0
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            artifact_ids = list({r[0] for r in rows})
            existing_pairs: set[tuple[UUID, UUID]] = set()
            result = await session.exec(
                select(
                    col(InfrastructureArtifactMentionTable.artifact_id),
                    col(InfrastructureArtifactMentionTable.message_id),
                ).where(col(InfrastructureArtifactMentionTable.artifact_id).in_(artifact_ids))
            )
            for aid, mid in result:
                existing_pairs.add((aid, mid))

            inserted = 0
            batch_seen: set[tuple[UUID, UUID]] = set()
            for artifact_id, message_id, char_offset, ts in rows:
                key = (artifact_id, message_id)
                if key in existing_pairs or key in batch_seen:
                    continue
                batch_seen.add(key)
                session.add(
                    InfrastructureArtifactMentionTable(
                        artifact_id=artifact_id,
                        message_id=message_id,
                        char_offset=char_offset,
                        ts=ts,
                    )
                )
                inserted += 1
            await session.commit()
            return inserted

    async def record_document_artifacts_bulk(
        self,
        rows: list[tuple[UUID, UUID, int | None, datetime]],
    ) -> int:
        """Bulk-insert document_artifact edges (artifact_id, document_id, char_offset,
        ts), skipping pairs already stored or duplicated within the batch. The
        document analogue of :meth:`record_artifact_mentions_bulk`."""
        if not rows:
            return 0
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            artifact_ids = list({r[0] for r in rows})
            existing_pairs: set[tuple[UUID, UUID]] = set()
            result = await session.exec(
                select(
                    col(DocumentArtifactTable.artifact_id),
                    col(DocumentArtifactTable.document_id),
                ).where(col(DocumentArtifactTable.artifact_id).in_(artifact_ids))
            )
            for aid, did in result:
                existing_pairs.add((aid, did))

            inserted = 0
            batch_seen: set[tuple[UUID, UUID]] = set()
            for artifact_id, document_id, char_offset, ts in rows:
                key = (artifact_id, document_id)
                if key in existing_pairs or key in batch_seen:
                    continue
                batch_seen.add(key)
                session.add(
                    DocumentArtifactTable(
                        artifact_id=artifact_id,
                        document_id=document_id,
                        char_offset=char_offset,
                        ts=ts,
                    )
                )
                inserted += 1
            await session.commit()
            return inserted

    async def record_document_artifacts(
        self,
        *,
        document_id: UUID,
        indicators: list[tuple[str, str, int | None]],
        now: datetime,
    ) -> int:
        """Upsert the artifacts extracted from a document's text and link each to the
        document. ``indicators`` = ``(kind, value, char_offset)``. Returns the number
        of NEW edges. Mirrors the message extraction path (bulk artifact upsert +
        bulk edge insert); used by the classifier (live) and the backfill CLI."""
        if not indicators:
            return 0
        hash_to_id = await self.put_infrastructure_artifacts_bulk(
            [(kind, value, now, now) for kind, value, _off in indicators]
        )
        edges = [
            (hash_to_id[_value_hash(value)], document_id, off, now)
            for _kind, value, off in indicators
        ]
        return await self.record_document_artifacts_bulk(edges)

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
