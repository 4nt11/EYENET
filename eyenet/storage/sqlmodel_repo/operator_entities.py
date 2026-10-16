# SPDX-License-Identifier: AGPL-3.0-or-later
"""OperatorEntitiesMixin — hand-created ("operator-asserted") graph entities.

Maltego-style operator nodes: an analyst drops an actor / group / artifact onto
the exploration canvas that no collector produced. Such entities carry
``provenance="operator_asserted"`` (vs the default ``"collected"``) and, because
actor/group require a ``source_id`` FK, hang off ONE synthetic ``SourceKind.OPERATOR``
source row (idempotently upserted). Artifacts have no required source FK and
dedup by ``value_hash`` — an operator asserting an already-collected artifact just
gets the existing row back.

Generic SQLModel ORM only (no dialect leak — [[feedback_no_dialect_leak_in_mixins]]).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlmodel import col, select

from eyenet.contracts.actor import actor_key
from eyenet.contracts.enums import GroupKind, SourceKind
from eyenet.models._base import new_uuid7
from eyenet.models.actor import ActorTable
from eyenet.models.group import GroupTable
from eyenet.models.infrastructure import InfrastructureArtifactTable

from ._helpers import safe_session
from .artifacts import _value_hash

_OPERATOR_PROVENANCE = "operator_asserted"
_OPERATOR_SOURCE_NAME = "Operator"


class OperatorEntitiesMixin:
    async def get_or_create_operator_source(self, *, now: datetime | None = None) -> UUID:
        """The single ``SourceKind.OPERATOR`` source that owns operator actors /
        groups. ``upsert_source`` is idempotent by (kind, display_name), so this
        is safe to call on every create."""
        source_id: UUID = await self.upsert_source(  # type: ignore[attr-defined]
            kind=SourceKind.OPERATOR,
            display_name=_OPERATOR_SOURCE_NAME,
            created_at=now or datetime.now(tz=UTC),
        )
        return source_id

    async def create_operator_actor(
        self,
        *,
        handle: str | None,
        display_name: str | None,
        now: datetime | None = None,
    ) -> UUID:
        """Create an operator-asserted actor. ``actor_key`` is derived from a fresh
        synthetic ``platform_userid`` so every operator actor is unique (no collision
        with collected actors, whose keys hash real platform ids)."""
        at = now or datetime.now(tz=UTC)
        source_id = await self.get_or_create_operator_source(now=at)
        synthetic_userid = f"op:{new_uuid7().hex}"
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            row = ActorTable(
                actor_key=actor_key(SourceKind.OPERATOR, synthetic_userid),
                source_id=source_id,
                platform_userid=synthetic_userid,
                current_handle=handle,
                current_display_name=display_name,
                first_seen_at_ingest=at,
                last_seen_at_ingest=at,
                first_seen_at_source=at,
                last_seen_at_source=at,
                provenance=_OPERATOR_PROVENANCE,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row.id

    async def create_operator_group(
        self,
        *,
        title: str | None,
        kind: GroupKind,
        now: datetime | None = None,
    ) -> UUID:
        """Create an operator-asserted group. The operator picks ``kind`` from the
        existing ``GroupKind`` set (chat / channel / forum_thread / ...)."""
        at = now or datetime.now(tz=UTC)
        source_id = await self.get_or_create_operator_source(now=at)
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            row = GroupTable(
                source_id=source_id,
                platform_groupid=f"op:{new_uuid7().hex}",
                kind=kind,
                current_title=title,
                first_seen_at_ingest=at,
                last_observed_at_ingest=at,
                provenance=_OPERATOR_PROVENANCE,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row.id

    async def create_operator_artifact(
        self,
        *,
        kind: str,
        value: str,
        now: datetime | None = None,
    ) -> UUID:
        """Create an operator-asserted artifact, or return the existing row if the
        value is already present (dedup by ``value_hash`` — an operator asserting an
        already-collected artifact references it, keeping its existing provenance)."""
        at = now or datetime.now(tz=UTC)
        vh = _value_hash(value)
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            existing = (
                await session.exec(
                    select(InfrastructureArtifactTable).where(
                        col(InfrastructureArtifactTable.value_hash) == vh
                    )
                )
            ).first()
            if existing is not None:
                return existing.id
            row = InfrastructureArtifactTable(
                kind=kind,
                value=value,
                value_hash=vh,
                first_seen_at_ingest=at,
                last_seen_at_ingest=at,
                provenance=_OPERATOR_PROVENANCE,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row.id


__all__ = ["OperatorEntitiesMixin"]
