# SPDX-License-Identifier: AGPL-3.0-or-later
"""Emit helper for entity-change events (GLOBAL_SEARCH.md §2.4).

One call site -> one line. Callers emit ONLY when the write actually changed
searchable content (e.g. ``upsert_actor`` returned ``search_changed=True``), so
this is not on the per-message hot path for unchanged rows.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from eyenet.contracts._base import TraceContext
from eyenet.contracts.search_events import EntityChangedEnvelope, entity_subject
from eyenet.telemetry.propagation import ZERO_TRACEPARENT, current_traceparent

if TYPE_CHECKING:
    from uuid import UUID

    from eyenet.bus.publisher import BusEnvelopePublisher


async def publish_entity_changed(
    publisher: BusEnvelopePublisher,
    *,
    entity_type: str,
    entity_id: UUID,
    source_id: UUID | None = None,
) -> None:
    """Publish ``entity.<type>.changed`` with the current trace context."""
    await publisher.publish(
        entity_subject(entity_type),
        EntityChangedEnvelope(
            entity_type=entity_type,
            entity_id=entity_id,
            source_id=source_id,
            trace_context=TraceContext(traceparent=current_traceparent() or ZERO_TRACEPARENT),
        ),
    )


__all__ = ["publish_entity_changed"]
