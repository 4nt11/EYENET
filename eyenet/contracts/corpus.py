"""`CorpusCursor` — sensor bookmark per (actor, primitive) (MODELS §2.16).

PLAN §5.3: cursor is per-PRIMITIVE, not per-actor. Different primitives have
different windows; sharing a single ts cursor would cause fast primitives to
skip messages that slow primitives haven't seen.

Composite PK `(actor_id, primitive_name)` is enforced in the SQLModel layer.
The Pydantic shape carries no `id` field — it's keyed by the composite,
which is why it does NOT extend `DbRowBase`.

Surface: db.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class CorpusCursorRow(BaseModel):
    """Sensor's cursor row. No surrogate UUID — composite key on (actor_id, primitive_name)."""

    model_config = ConfigDict(extra="forbid")

    actor_id: UUID
    primitive_name: str
    last_processed_msg_ts: datetime
    last_processed_msg_id: UUID


__all__ = ["CorpusCursorRow"]
