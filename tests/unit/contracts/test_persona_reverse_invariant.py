"""MODELS §2.6a — Persona forward view and PersonaMembership reverse view agree."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from eyenet.contracts.attribution import PersonaMembershipRow, PersonaRow

P = UUID("00000000-0000-0000-0000-0000000000aa")
A = UUID("00000000-0000-0000-0000-000000000001")
B = UUID("00000000-0000-0000-0000-000000000002")
C = UUID("00000000-0000-0000-0000-000000000003")
NOW = datetime(2026, 5, 4, tzinfo=UTC)


@pytest.mark.contract
def test_views_agree() -> None:
    persona = PersonaRow(
        id=P,
        member_actor_ids=[A, B, C],
        created_at=NOW,
        updated_at=NOW,
    )
    memberships = [
        PersonaMembershipRow(persona_id=P, actor_id=A, joined_at=NOW),
        PersonaMembershipRow(persona_id=P, actor_id=B, joined_at=NOW),
        PersonaMembershipRow(persona_id=P, actor_id=C, joined_at=NOW),
    ]
    forward = sorted(persona.member_actor_ids)
    reverse = sorted(m.actor_id for m in memberships if m.persona_id == P)
    assert forward == reverse


@pytest.mark.contract
def test_drift_detectable() -> None:
    persona = PersonaRow(
        id=P,
        member_actor_ids=[A, B],
        created_at=NOW,
        updated_at=NOW,
    )
    # Reverse view has an extra row → invariant violated.
    memberships = [
        PersonaMembershipRow(persona_id=P, actor_id=A, joined_at=NOW),
        PersonaMembershipRow(persona_id=P, actor_id=B, joined_at=NOW),
        PersonaMembershipRow(persona_id=P, actor_id=C, joined_at=NOW),
    ]
    forward = sorted(persona.member_actor_ids)
    reverse = sorted(m.actor_id for m in memberships if m.persona_id == P)
    assert forward != reverse
