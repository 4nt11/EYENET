# SPDX-License-Identifier: AGPL-3.0-or-later
"""IncidentsMixin — append-only incident classification results.

Generic SQLModel ORM only (no dialect-specific SQL): the table is append-only so the
bulk writer is a plain ANSI insert; no ON CONFLICT / upsert is needed. See
eyenet/models/incident.py and CLAUDE.md §2.3 (Rule 1: no dialect leak in mixins).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import String, cast as sql_cast, func, or_
from sqlmodel import col, select

from eyenet.contracts.incident import (
    IncidentLabelRow,
    IncidentRow,
    IncidentRuleRow,
    MessageGeoRow,
)
from eyenet.models import (
    GroupTable,
    IncidentLabelTable,
    IncidentRuleTable,
    IncidentTable,
    MessageGeoTable,
    MessageTable,
    SourceTable,
)

from ._helpers import safe_session


def _escape_like(term: str) -> str:
    """Escape LIKE wildcards so ``q`` matches literally (used with escape='\\')."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _model_incident_dict(m: IncidentTable) -> dict[str, Any]:
    return {
        "message_id": m.message_id,
        "labels": list(m.labels or []),
        "source": "model",
        "model_version": m.model_version,
        "scores": dict(m.scores or {}),
        "decided_by": None,
        "at": m.classified_at,
    }


def _operator_incident_dict(o: IncidentLabelTable) -> dict[str, Any]:
    return {
        "message_id": o.message_id,
        "labels": list(o.labels or []),
        "source": "operator",
        "model_version": None,
        "scores": {},
        "decided_by": o.decided_by,
        "at": o.decided_at,
    }


def _label_row(t: IncidentLabelTable) -> IncidentLabelRow:
    return IncidentLabelRow(
        message_id=t.message_id,
        labels=list(t.labels),
        reason=t.reason,
        decided_by=t.decided_by,
        decided_at=t.decided_at,
    )


def _geo_row(t: MessageGeoTable) -> MessageGeoRow:
    return MessageGeoRow(
        message_id=t.message_id,
        country=t.country,
        status=t.status,
        decided_by=t.decided_by,
        engine_version=t.engine_version,
        classified_at=t.classified_at,
    )


class IncidentsMixin:
    async def put_incidents_bulk(self, incident_rows: list[object]) -> None:
        """Persist many IncidentRows in ONE session — the classifier service's batch
        flush. Append-only; amortizes async-session overhead across the batch."""
        if not incident_rows:
            return
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            for r in incident_rows:
                row = cast("IncidentRow", r)
                session.add(IncidentTable(**row.model_dump()))
            await session.commit()

    async def incidents_for_message(self, message_id: UUID, limit: int = 10) -> list[object]:
        """Classification history for one message, latest run first."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = (
                select(IncidentTable)
                .where(IncidentTable.message_id == message_id)
                .order_by(col(IncidentTable.classified_at).desc())
                .limit(limit)
            )
            result = await session.exec(stmt)
            return list(result.all())

    async def effective_incident(self, message_id: UUID) -> dict[str, Any] | None:
        """The effective incident for a message: operator correction if present, else the
        latest model classification. ``labels`` may be [] (operator false-positive); None
        when the message has no classification at all. One incident per message."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            op = (
                await session.exec(
                    select(IncidentLabelTable).where(IncidentLabelTable.message_id == message_id)
                )
            ).first()
            if op is not None:
                return _operator_incident_dict(op)
            m = (
                await session.exec(
                    select(IncidentTable)
                    .where(IncidentTable.message_id == message_id)
                    .order_by(col(IncidentTable.classified_at).desc())
                    .limit(1)
                )
            ).first()
            return _model_incident_dict(m) if m is not None else None

    async def all_incident_message_ids(self) -> list[UUID]:
        """Every message id with a classification (model OR operator). Backfill iterator."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            a = set(await session.exec(select(IncidentTable.message_id)))
            b = set(await session.exec(select(IncidentLabelTable.message_id)))
            return list(a | b)

    async def all_effective_incidents(self) -> list[dict[str, Any]]:
        """Every non-empty effective incident (operator wins over model). Search-backfill
        bulk source. Loads only the sparse incident rows."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            ops = {o.message_id: o for o in await session.exec(select(IncidentLabelTable))}
            models: dict[UUID, IncidentTable] = {}
            for m in await session.exec(
                select(IncidentTable).order_by(col(IncidentTable.classified_at).desc())
            ):
                models.setdefault(m.message_id, m)
        out: list[dict[str, Any]] = []
        for mid in ops.keys() | models.keys():
            d = (
                _operator_incident_dict(ops[mid])
                if mid in ops
                else _model_incident_dict(models[mid])
            )
            if d["labels"]:
                out.append(d)
        return out

    async def effective_incidents_for_scope(
        self,
        *,
        message_id: UUID | None = None,
        group_id: UUID | None = None,
        actor_id: UUID | None = None,
        limit: int,
        offset: int,
        want_total: bool,
    ) -> tuple[list[dict[str, Any]], int | None, bool]:
        """Effective incidents (non-empty) for a scope: one message, a group/thread's
        messages, or an actor's messages. Operator correction wins over model; empties
        (false-positives) are excluded. Fetches only the sparse incident rows (joined to
        message for scope), builds the effective view + paginates in memory."""
        op_stmt = select(IncidentLabelTable)
        model_stmt = select(IncidentTable)
        if message_id is not None:
            op_stmt = op_stmt.where(IncidentLabelTable.message_id == message_id)
            model_stmt = model_stmt.where(IncidentTable.message_id == message_id)
        else:
            scope_col = MessageTable.group_id if group_id is not None else MessageTable.actor_id
            scope_val = group_id if group_id is not None else actor_id
            op_stmt = op_stmt.join(
                MessageTable, col(MessageTable.id) == col(IncidentLabelTable.message_id)
            ).where(col(scope_col) == scope_val)
            model_stmt = model_stmt.join(
                MessageTable, col(MessageTable.id) == col(IncidentTable.message_id)
            ).where(col(scope_col) == scope_val)
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            ops = {o.message_id: o for o in await session.exec(op_stmt)}
            models: dict[UUID, IncidentTable] = {}
            for m in await session.exec(
                model_stmt.order_by(col(IncidentTable.classified_at).desc())
            ):
                models.setdefault(m.message_id, m)  # first seen = latest
        effective: list[dict[str, Any]] = []
        for mid in ops.keys() | models.keys():
            d = (
                _operator_incident_dict(ops[mid])
                if mid in ops
                else _model_incident_dict(models[mid])
            )
            if d["labels"]:  # empty = operator false-positive -> not an incident
                effective.append(d)
        effective.sort(key=lambda d: d["at"] or _EPOCH, reverse=True)
        total = len(effective) if want_total else None
        page = effective[offset : offset + limit]
        return page, total, offset + limit < len(effective)

    def _apply_incident_filters(
        self,
        stmt: Any,
        *,
        labels: list[str] | None,
        q: str | None,
        group_ids: list[UUID] | None,
        source_ids: list[UUID] | None,
        victim_countries: list[str] | None = None,
        exclude_bodyless: bool = False,
        message_id: UUID | None = None,
    ) -> Any:
        """Apply the triage-feed filters to a SELECT over IncidentTable.

        Shared by :meth:`recent_incidents` and :meth:`count_incidents` so the
        page and its ``estimated_total`` can never drift apart. The caller owns
        the projection (rows vs COUNT), ordering, offset and limit; this only
        adds the WHERE/JOIN that both share.

        ``exclude_bodyless`` drops incidents whose message body is null/blank
        (pure-quote forum posts strip to empty and classify into content-less
        "row not retained" rows). Doing it IN SQL — not as a post-fetch Python
        filter — is what keeps offset paging honest (a page of ``limit`` returns
        ``limit`` real rows) and the count exact.
        # ponytail: SQL TRIM strips ASCII spaces; a body of only tabs/newlines
        # would count as non-blank here where Python str.strip() drops it. Rare
        # enough to accept; tighten with a char-class trim if it ever matters.
        """
        if message_id is not None:
            # Single-message lookup (the search inspector's incident block).
            stmt = stmt.where(col(IncidentTable.message_id) == message_id)
        if labels:
            # labels is a JSON array of clean identifiers; match the quoted token in its
            # text form. cast + LIKE are ANSI; each pattern is a bound param (no
            # injection). OR across the selected leaves (checkbox multi-select).
            stmt = stmt.where(
                or_(
                    *(
                        sql_cast(col(IncidentTable.labels), String).like(f'%"{lbl}"%')
                        for lbl in labels
                    )
                )
            )
        # q, group_ids, source_ids, exclude_bodyless all need the message; join ONCE.
        if q or group_ids or source_ids or exclude_bodyless:
            stmt = stmt.join(MessageTable, col(IncidentTable.message_id) == col(MessageTable.id))
        if q:
            # the free-text predicate is the dialect seam (_body_match): generic LIKE
            # here, FTS5 MATCH on SQLite, tsvector on a future Postgres backend.
            stmt = stmt.where(self._body_match(q))
        if group_ids:
            stmt = stmt.where(col(MessageTable.group_id).in_(group_ids))
        if source_ids:
            # Source-level filter: a forum's incidents all share one source
            # ("Darkforums") even though each thread is its own group.
            stmt = stmt.where(col(MessageTable.source_id).in_(source_ids))
        if exclude_bodyless:
            # length(trim(NULL)) is NULL (> 0 → false), so this drops null bodies too.
            stmt = stmt.where(func.length(func.trim(col(MessageTable.body))) > 0)
        if victim_countries:
            # Victim-country (geo) filter: join the message_geo sidecar (unique
            # message_id, so no row multiplication for the COUNT) and keep only the
            # resolved verdicts in the set. This is the "show me CL incidents"
            # filter — distinct from ?q= which is a body full-text search and never
            # matched the geo verdict.
            stmt = stmt.join(
                MessageGeoTable, col(IncidentTable.message_id) == col(MessageGeoTable.message_id)
            )
            stmt = stmt.where(col(MessageGeoTable.country).in_(victim_countries))
        return stmt

    async def recent_incidents(
        self,
        limit: int = 50,
        *,
        labels: list[str] | None = None,
        offset: int = 0,
        q: str | None = None,
        group_ids: list[UUID] | None = None,
        source_ids: list[UUID] | None = None,
        victim_countries: list[str] | None = None,
        exclude_bodyless: bool = False,
        message_id: UUID | None = None,
    ) -> list[object]:
        """Most recently classified incidents (operator triage feed). ``labels`` filters IN
        the query (OR: an incident matches if it carries ANY of the given leaves) so rare
        leaves are found regardless of overall recency (the old post-fetch filter hid rare
        labels below the limit); ``q`` free-text-matches the message body; ``group_ids``
        restricts to incidents whose message is in ONE of the given groups (show-only
        channels); ``victim_countries`` keeps only incidents whose geo verdict is one of the
        given ISO alpha-2 codes; ``exclude_bodyless`` drops content-less rows in SQL;
        ``offset`` pages. Newest first."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = self._apply_incident_filters(
                select(IncidentTable),
                labels=labels,
                q=q,
                group_ids=group_ids,
                source_ids=source_ids,
                victim_countries=victim_countries,
                exclude_bodyless=exclude_bodyless,
                message_id=message_id,
            )
            stmt = (
                stmt.order_by(col(IncidentTable.classified_at).desc()).offset(offset).limit(limit)
            )
            result = await session.exec(stmt)
            return list(result.all())

    async def count_incidents(
        self,
        *,
        labels: list[str] | None = None,
        q: str | None = None,
        group_ids: list[UUID] | None = None,
        source_ids: list[UUID] | None = None,
        victim_countries: list[str] | None = None,
        exclude_bodyless: bool = False,
        message_id: UUID | None = None,
    ) -> int:
        """Total incidents matching the same filters as :meth:`recent_incidents`
        (no offset/limit) — powers the triage feed's ``estimated_total`` so the
        operator sees the full match size, not just the capped current page."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = self._apply_incident_filters(
                select(func.count()).select_from(IncidentTable),
                labels=labels,
                q=q,
                group_ids=group_ids,
                source_ids=source_ids,
                victim_countries=victim_countries,
                exclude_bodyless=exclude_bodyless,
                message_id=message_id,
            )
            result = await session.exec(stmt)
            return int(result.one())

    async def incident_groups(self) -> list[tuple[UUID, str | None, UUID, int]]:
        """Distinct groups with at least one incident, as (group_id, title, source_id,
        incident_count), noisiest first — the feed's group filter (with source_id so the
        UI can scope the group list to a selected source). Generic ANSI: incident →
        message → group, GROUP BY + COUNT."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            count = func.count()
            stmt = (
                select(GroupTable.id, GroupTable.current_title, GroupTable.source_id, count)
                .select_from(IncidentTable)
                .join(MessageTable, col(IncidentTable.message_id) == col(MessageTable.id))
                .join(GroupTable, col(MessageTable.group_id) == col(GroupTable.id))
                .group_by(
                    col(GroupTable.id), col(GroupTable.current_title), col(GroupTable.source_id)
                )
                .order_by(count.desc())
            )
            result = await session.exec(stmt)
            return [
                (UUID(str(gid)), title, UUID(str(sid)), int(n))
                for gid, title, sid, n in result.all()
            ]

    async def incident_sources(self) -> list[tuple[UUID, str | None, int]]:
        """Distinct sources with at least one incident, as (source_id, display_name,
        count), noisiest first. The source-level feed filter — a forum's incidents
        roll up under one source ("Darkforums") instead of thousands of threads."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            count = func.count()
            stmt = (
                select(SourceTable.id, SourceTable.display_name, count)
                .select_from(IncidentTable)
                .join(MessageTable, col(IncidentTable.message_id) == col(MessageTable.id))
                .join(SourceTable, col(MessageTable.source_id) == col(SourceTable.id))
                .group_by(col(SourceTable.id), col(SourceTable.display_name))
                .order_by(count.desc())
            )
            result = await session.exec(stmt)
            return [(UUID(str(sid)), name, int(n)) for sid, name, n in result.all()]

    async def incident_countries(self) -> list[tuple[str, int]]:
        """Distinct resolved victim countries with at least one incident, as
        (country_alpha2, count), noisiest first — the feed's victim-country filter.
        incident → message_geo, GROUP BY country; NULL (mixed/unknown) excluded so
        the filter only offers codes that actually resolve to something."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            count = func.count()
            stmt = (
                select(MessageGeoTable.country, count)
                .select_from(IncidentTable)
                .join(
                    MessageGeoTable,
                    col(IncidentTable.message_id) == col(MessageGeoTable.message_id),
                )
                .where(col(MessageGeoTable.country).is_not(None))
                .group_by(col(MessageGeoTable.country))
                .order_by(count.desc())
            )
            result = await session.exec(stmt)
            return [(str(c), int(n)) for c, n in result.all()]

    def _body_match(self, q: str) -> Any:
        """Free-text predicate over the joined ``message.body``. Generic ANSI ``LIKE`` —
        full-scans bodies, correct on any backend and the fallback when a backend has no
        native FTS. Concrete backends override with dialect full-text search (SQLite →
        FTS5 MATCH, Postgres → tsvector @@ to_tsquery; CLAUDE.md §2.3 Rule 1)."""
        return col(MessageTable.body).like(f"%{_escape_like(q)}%", escape="\\")

    async def messages_without_incidents(
        self, *, limit: int = 500, after_id: UUID | None = None
    ) -> list[tuple[UUID, str]]:
        """(message_id, body) for messages with no incident row, oldest first (keyset
        by id). Generic ANSI: NOT IN a subquery over the append-only incident table."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            classified = select(IncidentTable.message_id)
            stmt = select(MessageTable.id, MessageTable.body).where(
                col(MessageTable.id).not_in(classified)
            )
            if after_id is not None:
                stmt = stmt.where(col(MessageTable.id) > after_id)
            stmt = stmt.order_by(col(MessageTable.id)).limit(limit)
            result = await session.exec(stmt)
            return [(mid, body) for mid, body in result]

    # ── victim-country attribution (geo sidecar, incident-flagged messages) ───
    async def messages_needing_geo(self, *, limit: int = 500) -> list[tuple[UUID, str, str | None]]:
        """(message_id, body, thread_title) for incident messages that have no geo row yet.

        A message counts as an incident if EITHER the classifier flagged it (a row in
        ``incident``) OR an operator asserted a non-empty true-label set via the reader (a
        ``incident_label`` row with labels != []). The operator channel matters: with a
        young classifier, real incidents are often hand-rescued, and those never get an
        ``incident`` row. Generic ANSI: message IN (model-flagged OR operator-labeled) and
        NOT IN the geo set; outer-join the group for its title. Oldest id first."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            model_flagged = select(IncidentTable.message_id)
            # labels is a JSON array; "[]" is the operator false-positive marker — exclude it.
            operator_labeled = select(IncidentLabelTable.message_id).where(
                sql_cast(col(IncidentLabelTable.labels), String) != "[]"
            )
            done = select(MessageGeoTable.message_id)
            stmt = (
                select(MessageTable.id, MessageTable.body, GroupTable.current_title)
                .join(GroupTable, col(MessageTable.group_id) == col(GroupTable.id), isouter=True)
                .where(
                    or_(
                        col(MessageTable.id).in_(model_flagged),
                        col(MessageTable.id).in_(operator_labeled),
                    )
                )
                .where(col(MessageTable.id).not_in(done))
                .order_by(col(MessageTable.id))
                .limit(limit)
            )
            result = await session.exec(stmt)
            return [(mid, body, title) for mid, body, title in result.all()]

    async def put_message_geo_bulk(self, geo_rows: list[object]) -> None:
        """Persist many MessageGeoRows in ONE session (the geo service's batch flush).
        Append-only; ``message_id`` is unique and the work queue only yields un-attributed
        messages, so a plain ANSI insert never conflicts."""
        if not geo_rows:
            return
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            for r in geo_rows:
                row = cast("MessageGeoRow", r)
                session.add(MessageGeoTable(**row.model_dump()))
            await session.commit()

    async def message_geo_by_message_ids(self, message_ids: list[UUID]) -> dict[UUID, object]:
        """Bulk {message_id: MessageGeoRow} for feed enrichment (mirrors the label join)."""
        if not message_ids:
            return {}
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            result = await session.exec(
                select(MessageGeoTable).where(col(MessageGeoTable.message_id).in_(message_ids))
            )
            return {t.message_id: _geo_row(t) for t in result.all()}

    # ── operator ground-truth label corrections (retraining signal) ──────────
    async def set_incident_label(
        self,
        message_id: UUID,
        labels: list[str],
        *,
        decided_by: str,
        reason: str | None,
        decided_at: datetime,
    ) -> object:
        """Upsert the operator's true label set for a message (SELECT-then-update-or-insert,
        generic ANSI — one current correction per message). ``labels`` may be empty."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            result = await session.exec(
                select(IncidentLabelTable).where(IncidentLabelTable.message_id == message_id)
            )
            row = result.first()
            if row is None:
                row = IncidentLabelTable(
                    message_id=message_id,
                    labels=labels,
                    reason=reason,
                    decided_by=decided_by,
                    decided_at=decided_at,
                )
            else:
                row.labels = labels
                row.reason = reason
                row.decided_by = decided_by
                row.decided_at = decided_at
            session.add(row)
            await session.commit()
            return _label_row(row)

    async def incident_labels_by_message_ids(self, message_ids: list[UUID]) -> dict[UUID, object]:
        """Bulk {message_id: IncidentLabelRow} for the current corrections (feed enrichment)."""
        if not message_ids:
            return {}
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            result = await session.exec(
                select(IncidentLabelTable).where(
                    col(IncidentLabelTable.message_id).in_(message_ids)
                )
            )
            return {t.message_id: _label_row(t) for t in result.all()}

    async def incident_labels_for_messages(self, message_ids: list[UUID]) -> dict[UUID, list[str]]:
        """Bulk {message_id: [labels]} from the CLASSIFIER's latest incident per message
        (not operator corrections). Enriches the reader so a post shows what it was
        tagged (e.g. data_breach). Messages with no incident are omitted."""
        if not message_ids:
            return {}
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            result = await session.exec(
                select(IncidentTable.message_id, IncidentTable.labels, IncidentTable.classified_at)
                .where(col(IncidentTable.message_id).in_(message_ids))
                .order_by(col(IncidentTable.classified_at).desc())
            )
            out: dict[UUID, list[str]] = {}
            for mid, labels, _ts in result.all():
                if mid not in out:  # desc order → first seen is the latest run
                    out[mid] = list(labels)
            return out

    async def all_incident_labels(self) -> list[object]:
        """Every operator correction (the retraining ground-truth export)."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            result = await session.exec(select(IncidentLabelTable))
            return [_label_row(t) for t in result.all()]

    # ── operator-defined detection rules (CRUD) ──────────────────────────────
    async def create_incident_rule(self, rule_row: object) -> None:
        row = cast("IncidentRuleRow", rule_row)
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            session.add(IncidentRuleTable(**row.model_dump()))
            await session.commit()

    async def list_incident_rules(self, *, enabled_only: bool = False) -> list[object]:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = select(IncidentRuleTable)
            if enabled_only:
                stmt = stmt.where(IncidentRuleTable.enabled == True)  # noqa: E712 — SQL boolean
            stmt = stmt.order_by(col(IncidentRuleTable.name))
            result = await session.exec(stmt)
            return list(result.all())

    async def get_incident_rule(self, rule_id: UUID) -> object | None:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            result = await session.exec(
                select(IncidentRuleTable).where(IncidentRuleTable.id == rule_id)
            )
            return result.first()

    async def update_incident_rule(self, rule_id: UUID, fields: dict[str, object]) -> bool:
        """SELECT-then-update (generic ANSI). Returns False if the rule doesn't exist."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            result = await session.exec(
                select(IncidentRuleTable).where(IncidentRuleTable.id == rule_id)
            )
            row = result.first()
            if row is None:
                return False
            for k, v in fields.items():
                setattr(row, k, v)
            session.add(row)
            await session.commit()
            return True

    async def delete_incident_rule(self, rule_id: UUID) -> bool:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            result = await session.exec(
                select(IncidentRuleTable).where(IncidentRuleTable.id == rule_id)
            )
            row = result.first()
            if row is None:
                return False
            await session.delete(row)
            await session.commit()
            return True
