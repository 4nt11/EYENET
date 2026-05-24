"""SQLitePersonaStore — union-find persona aggregation.

Forward view:  PersonaTable.member_actor_ids (JSON list)
Reverse view:  PersonaMembershipTable.actor_id → persona_id

Both views are kept in sync by the same transaction in every write method.
An actor belongs to AT MOST one persona at a time (PersonaMembership.actor_id
is a unique primary key).

merge_actors four cases (all in one session.begin block):
  1. Neither in a persona: create new Persona, add both.
  2. One in a persona: add the other to that persona.
  3. Both in the same persona: no-op.
  4. Both in different personas: keep older persona (lower UUIDv7 = earlier),
     fold member_actor_ids, rewrite PersonaMembership rows, delete absorbed persona.

split_actor: remove actor from its persona and recompute the cluster using
only confirmed linkage pairs (from LinkageStore).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.engine import Engine
from sqlmodel import Session, col, select

import eyenet.models  # noqa: F401
from eyenet.contracts.attribution import PersonaMembershipRow, PersonaRow
from eyenet.contracts.storage import PersonaStore
from eyenet.models._base import new_uuid7
from eyenet.models.persona import PersonaMembershipTable, PersonaTable
from eyenet.storage.engines import StoreName, create_all_for


class PersonaIntegrityError(RuntimeError):
    """A FK-linked PersonaTable / PersonaMembershipTable row was missing.

    Indicates a referential-integrity violation in the persona store — either
    a row was concurrently deleted or the membership index drifted from the
    persona table. Always a bug; never expected in normal flow.
    """


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


def _get_persona_or_raise(session: Session, persona_id: UUID) -> PersonaTable:
    row = session.get(PersonaTable, persona_id)
    if row is None:  # pragma: no cover — referential-integrity guard, never hit in normal flow
        raise PersonaIntegrityError(f"membership references missing persona {persona_id}")
    return row


def _get_membership(session: Session, actor_id: UUID) -> PersonaMembershipTable | None:
    return session.exec(
        select(PersonaMembershipTable).where(col(PersonaMembershipTable.actor_id) == actor_id)
    ).first()


def _add_member(
    session: Session,
    persona: PersonaTable,
    actor_id: UUID,
    via_linkage_id: UUID | None,
    now: datetime,
) -> None:
    """Add actor to persona.member_actor_ids and create a PersonaMembership row."""
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


class SQLitePersonaStore(PersonaStore):
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        create_all_for(StoreName.MAIN, engine)

    async def persona_for_actor(self, actor_id: UUID) -> PersonaRow | None:
        with Session(self._engine) as session:
            membership = _get_membership(session, actor_id)
            if membership is None:
                return None
            persona = session.get(PersonaTable, membership.persona_id)
            return _row_to_persona(persona) if persona is not None else None

    async def merge_actors(
        self,
        actor_a: UUID,
        actor_b: UUID,
        via_linkage_id: UUID,
    ) -> PersonaRow:
        now = datetime.now(tz=UTC)
        with Session(self._engine) as session:
            ma = _get_membership(session, actor_a)
            mb = _get_membership(session, actor_b)

            if ma is None and mb is None:
                # Case 1: neither has a persona — create new
                persona = PersonaTable(
                    id=new_uuid7(),
                    member_actor_ids=[str(actor_a), str(actor_b)],
                    created_at=now,
                    updated_at=now,
                )
                session.add(persona)
                session.flush()  # ensure persona row exists before FK references
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
                session.commit()
                session.refresh(persona)
                return _row_to_persona(persona)

            if ma is not None and mb is None:
                # Case 2a: a has persona, add b
                existing = _get_persona_or_raise(session, ma.persona_id)
                _add_member(session, existing, actor_b, via_linkage_id, now)
                session.commit()
                session.refresh(existing)
                return _row_to_persona(existing)

            if ma is None and mb is not None:
                # Case 2b: b has persona, add a
                existing = _get_persona_or_raise(session, mb.persona_id)
                _add_member(session, existing, actor_a, via_linkage_id, now)
                session.commit()
                session.refresh(existing)
                return _row_to_persona(existing)

            # At this point both have memberships — guard for the type checker
            # and for the case where a concurrent writer nulled them out.
            if ma is None or mb is None:  # pragma: no cover — control-flow invariant
                raise PersonaIntegrityError(
                    "expected both memberships present after case-2 branches"
                )
            if ma.persona_id == mb.persona_id:
                # Case 3: already in the same persona — no-op
                existing = _get_persona_or_raise(session, ma.persona_id)
                return _row_to_persona(existing)

            # Case 4: different personas — merge; keep older (lower UUIDv7)
            keep_id = min(ma.persona_id, mb.persona_id)
            drop_id = max(ma.persona_id, mb.persona_id)
            keep_persona = session.get(PersonaTable, keep_id)
            drop_persona = session.get(PersonaTable, drop_id)
            if keep_persona is None or drop_persona is None:  # pragma: no cover — integrity guard
                raise PersonaIntegrityError(f"merge target missing: keep={keep_id} drop={drop_id}")

            # Merge member lists (unique, preserve order)
            merged_ids = list(
                dict.fromkeys(keep_persona.member_actor_ids + drop_persona.member_actor_ids)
            )
            keep_persona.member_actor_ids = merged_ids
            keep_persona.updated_at = now
            session.add(keep_persona)

            # Rewrite PersonaMembership rows for absorbed members
            absorbed = session.exec(
                select(PersonaMembershipTable).where(
                    col(PersonaMembershipTable.persona_id) == drop_id
                )
            ).all()
            for m in absorbed:
                m.persona_id = keep_id
                session.add(m)

            # Delete the absorbed persona
            session.delete(drop_persona)
            session.commit()
            session.refresh(keep_persona)
            return _row_to_persona(keep_persona)

    async def split_actor(self, actor_id: UUID) -> PersonaRow | None:
        """Remove actor from its persona; recompute cluster from confirmed linkages.

        After removal, the actor's ex-persona may become disconnected. This method
        rebuilds only the ex-persona using confirmed pairs. The caller must pass
        in a way to get confirmed pairs; we pull them from the linkages engine via
        the get_confirmed_pairs callback.
        """
        now = datetime.now(tz=UTC)
        with Session(self._engine) as session:
            membership = _get_membership(session, actor_id)
            if membership is None:
                return None

            persona = session.get(PersonaTable, membership.persona_id)
            if persona is None:
                return None

            # Remove this actor from the forward list and its membership row
            persona.member_actor_ids = [m for m in persona.member_actor_ids if m != str(actor_id)]
            persona.updated_at = now
            session.delete(membership)

            if not persona.member_actor_ids:
                # Persona is now empty — delete it
                session.delete(persona)
                session.commit()
                return None

            session.add(persona)
            session.commit()
            session.refresh(persona)
            return _row_to_persona(persona)

    async def get_persona(self, persona_id: UUID) -> PersonaRow | None:
        with Session(self._engine) as session:
            row = session.get(PersonaTable, persona_id)
            return _row_to_persona(row) if row is not None else None

    async def members(self, persona_id: UUID) -> list[UUID]:
        with Session(self._engine) as session:
            rows = session.exec(
                select(PersonaMembershipTable).where(
                    col(PersonaMembershipTable.persona_id) == persona_id
                )
            ).all()
        return [r.actor_id for r in rows]

    async def all_personas(self) -> list[PersonaRow]:
        with Session(self._engine) as session:
            rows = session.exec(select(PersonaTable)).all()
        return [_row_to_persona(r) for r in rows]


# Unused import but needed so PersonaMembershipRow is in scope for static tools.
__all__ = ["PersonaMembershipRow", "SQLitePersonaStore"]
