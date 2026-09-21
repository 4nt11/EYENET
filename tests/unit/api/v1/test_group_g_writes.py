# SPDX-License-Identifier: AGPL-3.0-or-later
"""Direct-call unit tests for the M9 Group G write surface.

Handlers are called as plain coroutines with an in-memory repository, a
constructed CurrentUser, and a recording MemoryBus — the ASGI routing +
idempotency middleware are exercised separately (test_idempotency_middleware).
Covers: happy path (202 + durable event-log + bus publish), 404, and the
persona 422 semantic guards.
"""

from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

import pytest

from eyenet.api.deps import CurrentUser, ResourceNotFound, UnprocessableError
from eyenet.api.v1.identities.api_burn_identity import identities_burn
from eyenet.api.v1.identities.api_claim_identity import identities_claim
from eyenet.api.v1.identities.api_freeze_all import identities_freeze_all
from eyenet.api.v1.identities.api_freeze_identity import identities_freeze
from eyenet.api.v1.identities.api_release_identity import identities_release
from eyenet.api.v1.linkages.api_confirm_linkage import linkages_confirm
from eyenet.api.v1.panic.api_panic import control_panic
from eyenet.api.v1.personas.api_merge_persona import personas_merge
from eyenet.api.v1.personas.api_split_persona import personas_split
from eyenet.api.v1.schemas.identities import IdentityActionRequest, PanicRequest
from eyenet.api.v1.schemas.linkages import LinkageDecisionRequest
from eyenet.api.v1.schemas.personas import PersonaMergeRequest, PersonaSplitRequest
from eyenet.bus.memory import MemoryBus
from eyenet.bus.publisher import BusEnvelopePublisher
from eyenet.contracts.enums import IdentityState, LinkageState
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

pytestmark = pytest.mark.unit


async def _harness(storage: BaseRepository) -> tuple[AuditEmitter, BusEnvelopePublisher, list[str]]:
    bus = MemoryBus()
    publisher = BusEnvelopePublisher(bus)
    audit = AuditEmitter(publisher, storage, service="api", instance_id="api-0")
    seen: list[str] = []

    async def _rec(subject: str, _p: bytes, _h: dict[str, str]) -> None:
        seen.append(subject)

    await bus.subscribe(">", _rec)
    return audit, publisher, seen


async def _seed_identity(storage: BaseRepository):
    return await storage.create_identity(
        name=f"id-{uuid4().hex[:8]}", source_id=uuid4(), session_path="session.enc"
    )


# -- linkage -------------------------------------------------------------------


async def test_linkage_confirm_writes_event_log_and_publishes(
    storage: BaseRepository, mkuser: Callable[..., CurrentUser]
) -> None:
    a, b = sorted([uuid4(), uuid4()])
    linkage = await storage.insert_proposed_linkage(a, b, "stylometric", 0.9, {})
    audit, publisher, seen = await _harness(storage)
    user = mkuser("write:linkage_decision")

    result = await linkages_confirm(
        linkage_id=linkage.id,
        body=LinkageDecisionRequest(reason="same author"),
        current_user=user,
        storage=storage,
        audit=audit,
        publisher=publisher,
    )

    assert result.applied is False
    assert result.subject == "attribution.linkage.confirmed"
    assert result.poll == f"/v1/linkages/{linkage.id}"
    events = await storage.linkage_events(linkage.id)
    assert len(events) == 1
    assert events[0].event_subject == "attribution.linkage.confirmed"
    assert events[0].actor == str(user.user_id)
    assert events[0].traceparent
    # both the audit envelope and the domain event went to the bus
    assert "attribution.linkage.confirmed" in seen
    assert any(s.startswith("eyenet.audit.") for s in seen)


async def test_linkage_confirm_missing_is_404(
    storage: BaseRepository, mkuser: Callable[..., CurrentUser]
) -> None:
    audit, publisher, _ = await _harness(storage)
    with pytest.raises(ResourceNotFound):
        await linkages_confirm(
            linkage_id=uuid4(),
            body=LinkageDecisionRequest(reason="x"),
            current_user=mkuser("write:linkage_decision"),
            storage=storage,
            audit=audit,
            publisher=publisher,
        )


# -- identity ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("handler", "expected_state", "subject"),
    [
        (identities_claim, IdentityState.IN_USE, "eyenet.identity.claimed"),
        (identities_release, IdentityState.AVAILABLE, "eyenet.identity.released"),
        (identities_freeze, IdentityState.FROZEN, "eyenet.identity.frozen"),
        (identities_burn, IdentityState.BURNED, "eyenet.identity.burned"),
    ],
)
async def test_identity_action_persists_state(
    storage: BaseRepository,
    mkuser: Callable[..., CurrentUser],
    handler,
    expected_state,
    subject,
) -> None:
    identity = await _seed_identity(storage)
    audit, publisher, seen = await _harness(storage)

    result = await handler(
        body=IdentityActionRequest(reason="ops"),
        current_user=mkuser("write:identity"),
        storage=storage,
        audit=audit,
        publisher=publisher,
        identity_id=str(identity.id),
    )

    assert result.subject == subject
    after = await storage.get_identity(identity.id)
    assert after is not None and after.state is expected_state
    assert subject in seen
    events = await storage.identity_events(identity.id)
    assert len(events) == 1 and events[0].event_subject == subject


async def test_identity_action_bad_id_is_404(
    storage: BaseRepository, mkuser: Callable[..., CurrentUser]
) -> None:
    audit, publisher, _ = await _harness(storage)
    with pytest.raises(ResourceNotFound):
        await identities_claim(
            body=IdentityActionRequest(reason="x"),
            current_user=mkuser("write:identity"),
            storage=storage,
            audit=audit,
            publisher=publisher,
            identity_id="not-a-uuid",
        )


async def test_freeze_all_flips_non_terminal(
    storage: BaseRepository, mkuser: Callable[..., CurrentUser]
) -> None:
    i1 = await _seed_identity(storage)
    i2 = await _seed_identity(storage)
    await storage.burn_identity(identity_id=i2.id)  # terminal — must stay burned
    audit, publisher, seen = await _harness(storage)

    result = await identities_freeze_all(
        body=IdentityActionRequest(reason="lockdown"),
        current_user=mkuser("write:identity"),
        storage=storage,
        audit=audit,
        publisher=publisher,
    )

    assert result.subject == "eyenet.identity.freeze_all"
    assert (await storage.get_identity(i1.id)).state is IdentityState.FROZEN
    assert (await storage.get_identity(i2.id)).state is IdentityState.BURNED
    assert "eyenet.identity.freeze_all" in seen


# -- persona -------------------------------------------------------------------


async def test_persona_merge_happy_and_guards(
    storage: BaseRepository, mkuser: Callable[..., CurrentUser]
) -> None:
    # two distinct personas (each from a confirmed pair)
    p1 = await storage.merge_actors_into_persona(*sorted([uuid4(), uuid4()]))
    p2 = await storage.merge_actors_into_persona(*sorted([uuid4(), uuid4()]))
    audit, publisher, seen = await _harness(storage)
    user = mkuser("write:persona_decision")

    result = await personas_merge(
        persona_id=p1.id,
        body=PersonaMergeRequest(other_persona_id=p2.id, reason="same human"),
        current_user=user,
        storage=storage,
        audit=audit,
        publisher=publisher,
    )
    assert result.subject == "attribution.persona.merge"
    assert "attribution.persona.merge" in seen
    assert len(await storage.persona_events(p1.id)) == 1

    # merging into self → 422
    with pytest.raises(UnprocessableError):
        await personas_merge(
            persona_id=p1.id,
            body=PersonaMergeRequest(other_persona_id=p1.id, reason="x"),
            current_user=user,
            storage=storage,
            audit=audit,
            publisher=publisher,
        )
    # unknown path persona → 404
    with pytest.raises(ResourceNotFound):
        await personas_merge(
            persona_id=uuid4(),
            body=PersonaMergeRequest(other_persona_id=p2.id, reason="x"),
            current_user=user,
            storage=storage,
            audit=audit,
            publisher=publisher,
        )


async def test_persona_split_happy_and_nonmember(
    storage: BaseRepository, mkuser: Callable[..., CurrentUser]
) -> None:
    actor_a, actor_b = sorted([uuid4(), uuid4()])
    persona = await storage.merge_actors_into_persona(actor_a, actor_b)
    audit, publisher, seen = await _harness(storage)
    user = mkuser("write:persona_decision")

    result = await personas_split(
        persona_id=persona.id,
        body=PersonaSplitRequest(actor_id=actor_a, reason="over-linked"),
        current_user=user,
        storage=storage,
        audit=audit,
        publisher=publisher,
    )
    assert result.subject == "attribution.persona.split"
    assert "attribution.persona.split" in seen

    with pytest.raises(UnprocessableError):
        await personas_split(
            persona_id=persona.id,
            body=PersonaSplitRequest(actor_id=uuid4(), reason="x"),
            current_user=user,
            storage=storage,
            audit=audit,
            publisher=publisher,
        )


# -- panic ---------------------------------------------------------------------


async def test_panic_publishes_and_audits(
    storage: BaseRepository, mkuser: Callable[..., CurrentUser]
) -> None:
    audit, publisher, seen = await _harness(storage)
    result = await control_panic(
        body=PanicRequest(reason="breach", confirm="I_UNDERSTAND"),
        current_user=mkuser("write:panic"),
        audit=audit,
        publisher=publisher,
    )
    assert result.subject == "eyenet.control.panic"
    assert "eyenet.control.panic" in seen
    assert any(s.startswith("eyenet.audit.") for s in seen)


# -- linkage state is applied by Graph, not the API (invariant #2) -------------


async def test_confirm_does_not_apply_state_directly(
    storage: BaseRepository, mkuser: Callable[..., CurrentUser]
) -> None:
    a, b = sorted([uuid4(), uuid4()])
    linkage = await storage.insert_proposed_linkage(a, b, "m", 0.5, {})
    audit, publisher, _ = await _harness(storage)
    await linkages_confirm(
        linkage_id=linkage.id,
        body=LinkageDecisionRequest(reason="r"),
        current_user=mkuser("write:linkage_decision"),
        storage=storage,
        audit=audit,
        publisher=publisher,
    )
    # No Graph consumer here → linkage row stays PROPOSED (API never mutates it).
    still = await storage.get_linkage(linkage.id)
    assert still is not None and still.state is LinkageState.PROPOSED
