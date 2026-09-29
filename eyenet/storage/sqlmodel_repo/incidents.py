# SPDX-License-Identifier: AGPL-3.0-or-later
"""IncidentsMixin — append-only incident classification results.

Generic SQLModel ORM only (no dialect-specific SQL): the table is append-only so the
bulk writer is a plain ANSI insert; no ON CONFLICT / upsert is needed. See
eyenet/models/incident.py and CLAUDE.md §2.3 (Rule 1: no dialect leak in mixins).
"""

from __future__ import annotations

from datetime import datetime
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

    async def recent_incidents(
        self,
        limit: int = 50,
        *,
        labels: list[str] | None = None,
        offset: int = 0,
        q: str | None = None,
        group_ids: list[UUID] | None = None,
        source_ids: list[UUID] | None = None,
    ) -> list[object]:
        """Most recently classified incidents (operator triage feed). ``labels`` filters IN
        the query (OR: an incident matches if it carries ANY of the given leaves) so rare
        leaves are found regardless of overall recency (the old post-fetch filter hid rare
        labels below the limit); ``q`` free-text-matches the message body; ``group_ids``
        restricts to incidents whose message is in ONE of the given groups (show-only
        channels); ``offset`` pages. Newest first."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = select(IncidentTable)
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
            # q, group_ids, source_ids all need the message; join ONCE.
            if q or group_ids or source_ids:
                stmt = stmt.join(
                    MessageTable, col(IncidentTable.message_id) == col(MessageTable.id)
                )
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
            stmt = (
                stmt.order_by(col(IncidentTable.classified_at).desc()).offset(offset).limit(limit)
            )
            result = await session.exec(stmt)
            return list(result.all())

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
