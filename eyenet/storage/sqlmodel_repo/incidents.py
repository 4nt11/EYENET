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

from sqlalchemy import String, cast as sql_cast
from sqlmodel import col, select

from eyenet.contracts.incident import IncidentLabelRow, IncidentRow, IncidentRuleRow
from eyenet.models import IncidentLabelTable, IncidentRuleTable, IncidentTable, MessageTable

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
        self, limit: int = 50, *, label: str | None = None, offset: int = 0, q: str | None = None
    ) -> list[object]:
        """Most recently classified incidents (operator triage feed). ``label`` filters IN
        the query so a rare leaf is found regardless of overall recency (the old post-fetch
        filter hid rare labels below the limit); ``q`` free-text-matches the message body;
        ``offset`` pages. Newest first."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = select(IncidentTable)
            if label is not None:
                # labels is a JSON array of clean identifiers; match the quoted token in its
                # text form. cast + LIKE are ANSI; the pattern is a bound param (no injection).
                stmt = stmt.where(sql_cast(col(IncidentTable.labels), String).like(f'%"{label}"%'))
            if q:
                # incident → message join; the free-text predicate itself is the dialect
                # seam (_body_match): generic LIKE here, FTS5 MATCH on the SQLite backend,
                # tsvector on a future Postgres backend. Body only for now.
                stmt = stmt.join(
                    MessageTable, col(IncidentTable.message_id) == col(MessageTable.id)
                ).where(self._body_match(q))
            stmt = (
                stmt.order_by(col(IncidentTable.classified_at).desc()).offset(offset).limit(limit)
            )
            result = await session.exec(stmt)
            return list(result.all())

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
