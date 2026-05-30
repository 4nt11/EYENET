# SPDX-License-Identifier: AGPL-3.0-or-later
"""PersonasMixin — union-find aggregation over actors."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from eyenet.contracts.attribution import PersonaRow
from eyenet.models._base import new_uuid7
from eyenet.models.persona import PersonaMembershipTable, PersonaTable

from ._helpers import safe_session


class PersonaIntegrityError(RuntimeError):
    """A FK-linked persona row was missing — referential-integrity bug."""


def _row_to_persona(row: PersonaTable) -> PersonaRow:
    return PersonaRow(
        id=row.id,
        label=row.label,
        member_actor_ids=[UUID(str(aid)) for aid in row.member_actor_ids],
        created_at=row.created_at.replace(tzinfo=UTC)
        if row.created_at.tzinfo is None
        else row.created_at,
        updated_at=row.updated_at.replace(tzinfo=UTC)
        if row.updated_at.tzinfo is None
        else row.updated_at,
    )


async def _get_persona_or_raise(session: AsyncSession, persona_id: UUID) -> PersonaTable:
    row = await session.get(PersonaTable, persona_id)
    if row is None:
        raise PersonaIntegrityError(f"membership references missing persona {persona_id}")
    return row


async def _get_membership(session: AsyncSession, actor_id: UUID) -> PersonaMembershipTable | None:
    result = await session.exec(
        select(PersonaMembershipTable).where(col(PersonaMembershipTable.actor_id) == actor_id)
    )
    return result.first()


def _add_member(
    session: AsyncSession,
    persona: PersonaTable,
    actor_id: UUID,
    via_linkage_id: UUID | None,
    now: datetime,
) -> None:
    actor_str = str(actor_id)
    if actor_str not in persona.member_actor_ids:
        persona.member_actor_ids = [*persona.member_actor_ids, actor_str]
        persona.updated_at = now
        session.add(persona)
    membership = PersonaMembershipTable(
        persona_id=persona.id,
        actor_id=actor_id,
        joined_at=now,
        via_linkage_id=via_linkage_id,
    )
    session.add(membership)


class PersonasMixin:
    async def persona_for_actor(self, actor_id: UUID) -> PersonaRow | None:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            membership = await _get_membership(session, actor_id)
            if membership is None:
                return None
            persona = await session.get(PersonaTable, membership.persona_id)
            return _row_to_persona(persona) if persona is not None else None

    async def merge_actors_into_persona(
        self,
        actor_a: UUID,
        actor_b: UUID,
        via_linkage_id: UUID,
    ) -> PersonaRow:
        now = datetime.now(tz=UTC)
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            ma = await _get_membership(session, actor_a)
            mb = await _get_membership(session, actor_b)

            if ma is None and mb is None:
                persona = PersonaTable(
                    id=new_uuid7(),
                    member_actor_ids=[str(actor_a), str(actor_b)],
                    created_at=now,
                    updated_at=now,
                )
                session.add(persona)
                await session.flush()
                session.add(
                    PersonaMembershipTable(
                        persona_id=persona.id,
                        actor_id=actor_a,
                        joined_at=now,
                        via_linkage_id=via_linkage_id,
                    )
                )
                session.add(
                    PersonaMembershipTable(
                        persona_id=persona.id,
                        actor_id=actor_b,
                        joined_at=now,
                        via_linkage_id=via_linkage_id,
                    )
                )
                await session.commit()
                await session.refresh(persona)
                return _row_to_persona(persona)

            if ma is not None and mb is None:
                existing = await _get_persona_or_raise(session, ma.persona_id)
                _add_member(session, existing, actor_b, via_linkage_id, now)
                await session.commit()
                await session.refresh(existing)
                return _row_to_persona(existing)

            if ma is None and mb is not None:
                existing = await _get_persona_or_raise(session, mb.persona_id)
                _add_member(session, existing, actor_a, via_linkage_id, now)
                await session.commit()
                await session.refresh(existing)
                return _row_to_persona(existing)

            if ma is None or mb is None:  # pragma: no cover — control-flow invariant
                raise PersonaIntegrityError(
                    "expected both memberships present after case-2 branches"
                )
            if ma.persona_id == mb.persona_id:
                existing = await _get_persona_or_raise(session, ma.persona_id)
                return _row_to_persona(existing)

            keep_id = min(ma.persona_id, mb.persona_id)
            drop_id = max(ma.persona_id, mb.persona_id)
            keep_persona = await session.get(PersonaTable, keep_id)
            drop_persona = await session.get(PersonaTable, drop_id)
            if keep_persona is None or drop_persona is None:
                raise PersonaIntegrityError(f"merge target missing: keep={keep_id} drop={drop_id}")

            merged_ids = list(
                dict.fromkeys(keep_persona.member_actor_ids + drop_persona.member_actor_ids)
            )
            keep_persona.member_actor_ids = merged_ids
            keep_persona.updated_at = now
            session.add(keep_persona)

            absorbed_result = await session.exec(
                select(PersonaMembershipTable).where(
                    col(PersonaMembershipTable.persona_id) == drop_id
                )
            )
            for m in list(absorbed_result):
                m.persona_id = keep_id
                session.add(m)

            await session.delete(drop_persona)
            await session.commit()
            await session.refresh(keep_persona)
            return _row_to_persona(keep_persona)

    async def split_actor_from_persona(self, actor_id: UUID) -> PersonaRow | None:
        now = datetime.now(tz=UTC)
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            membership = await _get_membership(session, actor_id)
            if membership is None:
                return None

            persona = await session.get(PersonaTable, membership.persona_id)
            if persona is None:
                return None

            persona.member_actor_ids = [m for m in persona.member_actor_ids if m != str(actor_id)]
            persona.updated_at = now
            await session.delete(membership)

            if not persona.member_actor_ids:
                await session.delete(persona)
                await session.commit()
                return None

            session.add(persona)
            await session.commit()
            await session.refresh(persona)
            return _row_to_persona(persona)

    async def get_persona(self, persona_id: UUID) -> PersonaRow | None:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            row = await session.get(PersonaTable, persona_id)
            return _row_to_persona(row) if row is not None else None

    async def persona_members(self, persona_id: UUID) -> list[UUID]:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            result = await session.exec(
                select(PersonaMembershipTable).where(
                    col(PersonaMembershipTable.persona_id) == persona_id
                )
            )
            rows = list(result)
        return [r.actor_id for r in rows]

    async def list_persona_memberships(
        self,
        persona_id: UUID,
        *,
        limit: int,
        offset: int = 0,
    ) -> list[object]:
        """Membership rows for a persona, oldest-join-first (M9.F1).

        Returns ``PersonaMembershipTable`` rows (type-erased to ``object``) so
        the members projector can surface ``joined_at`` and ``via_linkage_id``
        — richer than ``persona_members`` which yields only actor ids.
        """
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            result = await session.exec(
                select(PersonaMembershipTable)
                .where(col(PersonaMembershipTable.persona_id) == persona_id)
                .order_by(col(PersonaMembershipTable.joined_at))
                .order_by(col(PersonaMembershipTable.actor_id))
                .limit(limit)
                .offset(offset)
            )
            return list(result)

    async def count_persona_memberships(self, persona_id: UUID) -> int:
        """Count membership rows for a persona (M9.F1)."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            result = await session.exec(
                select(func.count())
                .select_from(PersonaMembershipTable)
                .where(col(PersonaMembershipTable.persona_id) == persona_id)
            )
            return int(result.one())

    async def count_personas(self) -> int:
        """Total number of personas (M9.F3 graph stats)."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            result = await session.exec(select(func.count()).select_from(PersonaTable))
            return int(result.one())

    async def all_personas(self) -> list[object]:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            result = await session.exec(select(PersonaTable))
            rows = list(result)
        return [_row_to_persona(r) for r in rows]


__all__ = ["PersonaIntegrityError", "PersonasMixin"]
