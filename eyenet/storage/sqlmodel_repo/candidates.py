# SPDX-License-Identifier: AGPL-3.0-or-later
"""CandidatesMixin — GroupCandidate + GroupCandidateMention CRUD (API_PLAN §4.12, M9.C4).

ANSI SQL only (CLAUDE.md §2.3 Rule 1). Idempotent mention upsert via
SELECT-before-INSERT (no ON CONFLICT). State guard via the _ALLOWED transition
map — every illegal edge raises ValueError before touching the database.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func
from sqlmodel import col, select
from sqlmodel.sql.expression import SelectOfScalar

from eyenet.contracts.candidate import (
    EligibilityInputs,
    GroupCandidateMentionRow,
    GroupCandidateRow,
)
from eyenet.contracts.enums import CandidateState, GroupKind, MentionKind
from eyenet.models.candidates import GroupCandidateMentionTable, GroupCandidateTable
from eyenet.models.case import CaseTable
from eyenet.models.membership import CollectorGroupMembershipTable

from ._helpers import safe_session

# Legal state transitions per MODELS §2.20 state machine diagram.
_ALLOWED: dict[CandidateState, frozenset[CandidateState]] = {
    CandidateState.DISCOVERED: frozenset({CandidateState.QUEUED, CandidateState.REJECTED}),
    CandidateState.QUEUED: frozenset({CandidateState.APPROVED, CandidateState.REJECTED}),
    CandidateState.APPROVED: frozenset({CandidateState.JOINING, CandidateState.REJECTED}),
    CandidateState.JOINING: frozenset({CandidateState.JOINED, CandidateState.FAILED}),
    CandidateState.JOINED: frozenset({CandidateState.PARKED}),
    # FAILED → QUEUED is the M9.D3 retry edge (admin:candidates, can burn an
    # identity); FAILED → PARKED is the give-up edge.
    CandidateState.FAILED: frozenset({CandidateState.PARKED, CandidateState.QUEUED}),
    CandidateState.REJECTED: frozenset({CandidateState.PARKED}),
    CandidateState.PARKED: frozenset({CandidateState.APPROVED}),
}


def _coerce_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _candidate_row(table: GroupCandidateTable) -> GroupCandidateRow:
    data = table.model_dump()
    for k in (
        "first_observed_at_ingest",
        "last_observed_at_ingest",
        "reviewed_at",
    ):
        data[k] = _coerce_utc(data.get(k))
    return GroupCandidateRow.model_validate(data)


def _mention_row(table: GroupCandidateMentionTable) -> GroupCandidateMentionRow:
    data = table.model_dump()
    for k in ("mentioned_at_source", "mentioned_at_ingest"):
        data[k] = _coerce_utc(data.get(k))
    return GroupCandidateMentionRow.model_validate(data)


class CandidatesMixin:
    """CRUD + state-write surface for GroupCandidate and GroupCandidateMention."""

    async def record_candidate_mention(
        self,
        *,
        source_id: UUID,
        platform_groupid: str,
        observed_by_collector_id: UUID,
        observed_in_group_id: UUID,
        seed_root_id: UUID | None,
        depth_from_root: int,
        mention_evidence_ref: str,
        mention_kind: MentionKind,
        mentioned_at_source: datetime,
        mentioned_at_ingest: datetime,
        mentioning_actor_id: UUID,
        mentioning_actor_role_signal: str | None = None,
        kind_hint: GroupKind | None = None,
        display_name_hint: str | None = None,
    ) -> tuple[GroupCandidateRow, GroupCandidateMentionRow]:
        """Upsert a GroupCandidate and append a mention provenance row.

        The candidate is looked up by ``(source_id, platform_groupid)``;
        created as DISCOVERED if not yet present. The mention is idempotent:
        a second call with the same ``(source_id + platform_groupid, mention_evidence_ref)``
        returns the existing mention row without inserting a duplicate.

        ``last_observed_at_ingest`` on the candidate is bumped if the new
        mention is more recent than the stored value.
        """
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            # 1. Look up or create the candidate.
            stmt = select(GroupCandidateTable).where(
                GroupCandidateTable.source_id == source_id,
                GroupCandidateTable.platform_groupid == platform_groupid,
            )
            result = await session.exec(stmt)
            candidate = result.one_or_none()

            if candidate is None:
                candidate = GroupCandidateTable(
                    source_id=source_id,
                    platform_groupid=platform_groupid,
                    kind_hint=kind_hint,
                    display_name_hint=display_name_hint,
                    state=CandidateState.DISCOVERED,
                    score=0.0,
                    score_breakdown={},
                    score_function_version=1,
                    first_observed_at_ingest=mentioned_at_ingest,
                    last_observed_at_ingest=mentioned_at_ingest,
                )
                session.add(candidate)
                await session.flush()  # populate candidate.id before mention FK
            elif mentioned_at_ingest > (
                # SQLite returns tz-naive; coerce before comparing with the
                # tz-aware caller value.
                _coerce_utc(candidate.last_observed_at_ingest) or mentioned_at_ingest
            ):
                candidate.last_observed_at_ingest = mentioned_at_ingest
                session.add(candidate)

            # 2. Look up existing mention (idempotent guard).
            mention_stmt = select(GroupCandidateMentionTable).where(
                GroupCandidateMentionTable.candidate_id == candidate.id,
                GroupCandidateMentionTable.mention_evidence_ref == mention_evidence_ref,
            )
            mention_result = await session.exec(mention_stmt)
            mention = mention_result.one_or_none()

            if mention is None:
                mention = GroupCandidateMentionTable(
                    candidate_id=candidate.id,
                    observed_by_collector_id=observed_by_collector_id,
                    observed_in_group_id=observed_in_group_id,
                    seed_root_id=seed_root_id,
                    depth_from_root=depth_from_root,
                    mention_evidence_ref=mention_evidence_ref,
                    mention_kind=mention_kind,
                    mentioned_at_source=mentioned_at_source,
                    mentioned_at_ingest=mentioned_at_ingest,
                    mentioning_actor_id=mentioning_actor_id,
                    mentioning_actor_role_signal=mentioning_actor_role_signal,
                )
                session.add(mention)

            await session.commit()
            await session.refresh(candidate)
            await session.refresh(mention)
            return _candidate_row(candidate), _mention_row(mention)

    async def get_candidate(self, candidate_id: UUID) -> GroupCandidateRow | None:
        """Return one GroupCandidateRow by id, or ``None``."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            table = await session.get(GroupCandidateTable, candidate_id)
            return _candidate_row(table) if table is not None else None

    async def list_queued_candidates(
        self,
        *,
        source_id: UUID | None = None,
    ) -> list[GroupCandidateRow]:
        """Return QUEUED candidates ordered by score DESC.

        Pass ``source_id`` to restrict to one Source; omit for all Sources.
        """
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = select(GroupCandidateTable).where(
                GroupCandidateTable.state == CandidateState.QUEUED,
            )
            if source_id is not None:
                stmt = stmt.where(GroupCandidateTable.source_id == source_id)
            stmt = stmt.order_by(col(GroupCandidateTable.score).desc())
            result = await session.exec(stmt)
            return [_candidate_row(r) for r in list(result)]

    def _filtered_stmt(
        self,
        *,
        state: CandidateState | None,
        source_id: UUID | None,
        min_score: float | None,
    ) -> SelectOfScalar[GroupCandidateTable]:
        stmt = select(GroupCandidateTable)
        if state is not None:
            stmt = stmt.where(GroupCandidateTable.state == state)
        if source_id is not None:
            stmt = stmt.where(GroupCandidateTable.source_id == source_id)
        if min_score is not None:
            stmt = stmt.where(col(GroupCandidateTable.score) >= min_score)
        return stmt

    async def list_candidates(
        self,
        *,
        state: CandidateState | None = None,
        source_id: UUID | None = None,
        min_score: float | None = None,
        limit: int,
        offset: int = 0,
    ) -> list[GroupCandidateRow]:
        """Triage queue (API_PLAN §4.12) — generalized over
        :meth:`list_queued_candidates` (which is QUEUED-only).

        Filters compose (AND). Sort: ``score DESC, last_observed_at_ingest
        DESC`` — the operator's most-signal-first triage order.
        """
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = (
                self._filtered_stmt(state=state, source_id=source_id, min_score=min_score)
                .order_by(
                    col(GroupCandidateTable.score).desc(),
                    col(GroupCandidateTable.last_observed_at_ingest).desc(),
                )
                .offset(offset)
                .limit(limit)
            )
            result = await session.exec(stmt)
            return [_candidate_row(r) for r in list(result)]

    async def count_candidates(
        self,
        *,
        state: CandidateState | None = None,
        source_id: UUID | None = None,
        min_score: float | None = None,
    ) -> int:
        """Count candidates matching the same filters as :meth:`list_candidates`."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            inner = self._filtered_stmt(
                state=state, source_id=source_id, min_score=min_score
            ).subquery()
            result = await session.exec(select(func.count()).select_from(inner))
            return int(result.one())

    async def transition_candidate(
        self,
        *,
        candidate_id: UUID,
        to_state: CandidateState,
        reviewed_by: str | None = None,
        reviewed_at: datetime | None = None,
        rejection_reason: str | None = None,
        assigned_collector_id: UUID | None = None,
        resulting_group_id: UUID | None = None,
    ) -> GroupCandidateRow:
        """Apply a state transition to a GroupCandidate (state guard enforced).

        Raises :class:`ValueError` if the transition is not in the legal set
        for the current state, or if the candidate does not exist.

        ``reviewed_by`` / ``reviewed_at`` should be set on all operator-driven
        transitions (approve, reject, park). ``assigned_collector_id`` is
        set on the ``approved`` transition. ``resulting_group_id`` is set on
        the ``joined`` transition.
        """
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            candidate = await session.get(GroupCandidateTable, candidate_id)
            if candidate is None:
                raise ValueError(f"candidate {candidate_id} not found")

            from_state: CandidateState = candidate.state
            allowed = _ALLOWED.get(from_state, frozenset())
            if to_state not in allowed:
                raise ValueError(
                    f"illegal candidate transition {from_state!r} → {to_state!r}; "
                    f"allowed from {from_state!r}: {sorted(s.value for s in allowed)}"
                )

            candidate.state = to_state
            if reviewed_by is not None:
                candidate.reviewed_by = reviewed_by
            if reviewed_at is not None:
                candidate.reviewed_at = reviewed_at
            if rejection_reason is not None:
                candidate.rejection_reason = rejection_reason
            if assigned_collector_id is not None:
                candidate.assigned_collector_id = assigned_collector_id
            if resulting_group_id is not None:
                candidate.resulting_group_id = resulting_group_id

            session.add(candidate)
            await session.commit()
            await session.refresh(candidate)
            return _candidate_row(candidate)

    async def compute_eligibility_inputs(
        self,
        candidate_id: UUID,
    ) -> EligibilityInputs:
        """Return pre-computed eligibility inputs for a candidate (API_PLAN §4.12.3).

        ``min_depth_by_collector`` maps each collector_id that has a mention
        for this candidate to the minimum ``depth_from_root`` across all its
        mentions. The caller (M9.D3 eligibility predicate) evaluates
        ``min_depth_by_collector[C.id] <= C.config.max_auto_join_depth``.

        Raises :class:`ValueError` if the candidate does not exist.
        """
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            candidate = await session.get(GroupCandidateTable, candidate_id)
            if candidate is None:
                raise ValueError(f"candidate {candidate_id} not found")

            mention_stmt = select(GroupCandidateMentionTable).where(
                GroupCandidateMentionTable.candidate_id == candidate_id,
            )
            mention_result = await session.exec(mention_stmt)
            mention_tables = list(mention_result)
            mentions = [_mention_row(m) for m in mention_tables]

            min_depth: dict[UUID, int] = {}
            for m in mentions:
                cid = m.observed_by_collector_id
                min_depth[cid] = min(min_depth.get(cid, m.depth_from_root), m.depth_from_root)

            return EligibilityInputs(
                candidate=_candidate_row(candidate),
                mentions=mentions,
                min_depth_by_collector=min_depth,
            )

    async def group_lineage(self, group_id: UUID) -> tuple[UUID | None, int]:
        """Return ``(seed_root_id, depth_from_root)`` for a group (API_PLAN §4.12).

        Resolution order:

        1. **Seed root** — the group is listed in some Case's
           ``seed_root_group_ids`` → ``(group_id, 0)``.
        2. **Discovered** — a candidate's ``resulting_group_id`` points here →
           the min-depth mention of that candidate carries the lineage
           ``(seed_root_id, depth_from_root)``.
        3. **Unknown** — neither (a seed/manual group not registered as a root)
           → ``(None, 0)``. Mentions extracted from it cannot propagate a root.

        Used by ``channel_reference_extraction`` (E2): a mention observed in
        group G gets ``seed_root_id = root`` and ``depth_from_root = depth + 1``.
        """
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            gid = str(group_id)
            case_result = await session.exec(select(CaseTable))
            for case_table in case_result:
                if gid in case_table.seed_root_group_ids:
                    return (group_id, 0)

            cand_stmt = select(GroupCandidateTable).where(
                col(GroupCandidateTable.resulting_group_id) == group_id,
            )
            candidate = (await session.exec(cand_stmt)).first()
            if candidate is not None:
                mention_stmt = select(GroupCandidateMentionTable).where(
                    col(GroupCandidateMentionTable.candidate_id) == candidate.id,
                    col(GroupCandidateMentionTable.seed_root_id).is_not(None),
                )
                mentions = list(await session.exec(mention_stmt))
                if mentions:
                    best = min(mentions, key=lambda m: m.depth_from_root)
                    return (best.seed_root_id, best.depth_from_root)

            return (None, 0)

    async def reachable_roots_for_collector(self, collector_id: UUID) -> set[UUID]:
        """Return the seed-root group ids reachable by a collector (§4.12.3).

        A root is reachable when the collector has either (a) observed a mention
        carrying that ``seed_root_id``, or (b) an active membership in a group
        that is itself a registered seed root. The eligibility predicate
        intersects this set with a candidate's mention seed-roots to find the
        minimum reachable depth.
        """
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            roots: set[UUID] = set()

            mention_stmt = select(GroupCandidateMentionTable.seed_root_id).where(
                col(GroupCandidateMentionTable.observed_by_collector_id) == collector_id,
                col(GroupCandidateMentionTable.seed_root_id).is_not(None),
            )
            for seed_root_id in await session.exec(mention_stmt):
                if seed_root_id is not None:
                    roots.add(seed_root_id)

            mem_stmt = select(CollectorGroupMembershipTable.group_id).where(
                col(CollectorGroupMembershipTable.collector_id) == collector_id,
                col(CollectorGroupMembershipTable.left_at).is_(None),
            )
            member_group_ids = set(await session.exec(mem_stmt))
            if member_group_ids:
                seed_set: set[str] = set()
                for case_table in await session.exec(select(CaseTable)):
                    seed_set.update(case_table.seed_root_group_ids)
                roots.update(g for g in member_group_ids if str(g) in seed_set)

            return roots


__all__ = ["CandidatesMixin"]
