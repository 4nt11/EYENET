# SPDX-License-Identifier: AGPL-3.0-or-later
"""Assemble the per-actor circadian panel (histograms + timezone inference).

Read-time: pulls the latest circadian.* + lexical.dialect_region observations and
runs the pure inference. Returns None when the actor has no circadian data yet.
"""

from __future__ import annotations

from typing import cast
from uuid import UUID

from eyenet.api.v1.schemas.actors import ActorCircadian, InferredTimezone
from eyenet.engine.timezone_inference import infer_timezone
from eyenet.models.observation import ObservationTable
from eyenet.storage.repository import BaseRepository

_QUIET_SPAN_LEN = 2


async def _latest_array(storage: BaseRepository, actor_id: UUID, name: str) -> list[float] | None:
    rows = await storage.latest_observations(actor_id, name, limit=1)
    if not rows:
        return None
    return cast("ObservationTable", rows[0]).value_array_numeric


async def _latest_enum(storage: BaseRepository, actor_id: UUID, name: str) -> str | None:
    rows = await storage.latest_observations(actor_id, name, limit=1)
    if not rows:
        return None
    return cast("ObservationTable", rows[0]).value_enum


async def build_actor_circadian(
    storage: BaseRepository, actor_id: UUID
) -> ActorCircadian | None:
    hour = await _latest_array(storage, actor_id, "circadian.hour_histogram")
    if not hour:
        return None  # no circadian data for this actor yet

    dow = await _latest_array(storage, actor_id, "circadian.dow_histogram") or []
    joint = await _latest_array(storage, actor_id, "circadian.hour_dow_histogram") or []
    qs = await _latest_array(storage, actor_id, "circadian.quiet_span_utc")
    quiet = (int(qs[0]), int(qs[1])) if qs and len(qs) >= _QUIET_SPAN_LEN else None

    dialect = await _latest_enum(storage, actor_id, "lexical.dialect_region")
    total_messages = await storage.count_messages_for_actor(actor_id)

    tz = infer_timezone(
        hour_histogram=hour,
        quiet_span_utc=quiet,
        total_messages=total_messages,
        dialect_region=dialect,
    )
    return ActorCircadian(
        hour_histogram=hour,
        dow_histogram=dow,
        hour_dow_histogram=joint,
        quiet_span_utc=quiet,
        inferred_tz=InferredTimezone(
            offset_hours=tz.offset_hours,
            zone_best=tz.zone_best,
            zone_candidates=tz.zone_candidates,
            confidence=tz.confidence,
            supporting_signals=tz.supporting_signals,
            local_active_window=tz.local_active_window,
            quiet_window_utc=tz.quiet_window_utc,
        ),
    )
