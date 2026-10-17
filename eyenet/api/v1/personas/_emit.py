# SPDX-License-Identifier: AGPL-3.0-or-later
"""Emit ``attribution.persona.updated`` for the DIRECT (synchronous) operator persona
writes from the graph canvas - standalone create, add member, remove member.

The merge/split COMMAND flow has the Graph service (the single persona writer) emit this
event after applying the union-find. These graph-canvas routes apply the mutation inline
for immediate feedback, so they must emit it themselves - that event is what drives the
search_indexer to (re)index the persona, without which it never appears in hydrate/search.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from eyenet.contracts._base import TraceContext
from eyenet.contracts.attribution import (
    SUBJECT_PERSONA_UPDATED,
    PersonaChangeKind,
    PersonaUpdatedEnvelope,
)
from eyenet.telemetry.propagation import ZERO_TRACEPARENT, current_traceparent

if TYPE_CHECKING:
    from eyenet.bus.publisher import BusEnvelopePublisher


async def emit_persona_updated(
    publisher: BusEnvelopePublisher,
    *,
    persona_id: UUID,
    member_actor_ids: list[UUID],
    change_kind: PersonaChangeKind,
) -> None:
    await publisher.publish(
        SUBJECT_PERSONA_UPDATED,
        PersonaUpdatedEnvelope(
            persona_id=persona_id,
            member_actor_ids=member_actor_ids,
            change_kind=change_kind,
            at=datetime.now(tz=UTC),
            trace_context=TraceContext(traceparent=current_traceparent() or ZERO_TRACEPARENT),
        ),
    )
