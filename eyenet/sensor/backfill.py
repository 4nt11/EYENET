# SPDX-License-Identifier: AGPL-3.0-or-later
"""Circadian primitive backfill over the existing corpus.

The circadian.* primitives are full-corpus RECOMPUTE primitives: they derive
from one pass over an actor's whole message history, not message-by-message. So
backfilling them is O(actors), not O(messages) — fetch each actor's corpus once
and compute, rather than replaying the bus. Live actors get circadian on their
next message automatically; this command is for the dormant/historical corpus.

Idempotent by default: an actor that already has a circadian.hour_histogram
observation is skipped (observations append, never upsert), so a re-run does not
stack duplicate rows. Pass force=True to recompute regardless.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from eyenet.sensor.primitives import PRIMITIVES
from eyenet.sensor.stylometric import _observation_to_row
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.logging import get_logger

_log = get_logger()

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_NULL_UUID = UUID("00000000-0000-0000-0000-000000000000")
_CANARY_PRIMITIVE = "circadian.hour_histogram"
_SENSOR_INSTANCE = "sensor-backfill"

# The circadian.* specs only (timestamp-derived, requires_bodies=False): the cheap
# subset to backfill. meta.* already landed with its milestone; the spaCy/locale
# full-corpus primitives are deliberately NOT replayed here (they'd push the whole
# corpus through the tagger).
_CIRCADIAN_SPECS = tuple(s for s in PRIMITIVES if s.name.startswith("circadian."))


@dataclass
class BackfillResult:
    actors_processed: int = 0
    actors_skipped: int = 0
    observations_written: int = 0


async def _backfill_actor(
    storage: BaseRepository, actor_id: UUID, *, force: bool, result: BackfillResult
) -> None:
    if not force:
        existing = await storage.latest_observations(actor_id, _CANARY_PRIMITIVE, limit=1)
        if existing:
            result.actors_skipped += 1
            return

    corpus = await storage.iter_corpus_since(actor_id, _EPOCH, _NULL_UUID)
    if not corpus:
        result.actors_skipped += 1
        return

    rows: list[object] = []
    for spec in _CIRCADIAN_SPECS:
        obs = spec.compute(corpus=corpus, bodies={})
        if obs is not None:
            rows.append(_observation_to_row(obs, actor_id, _SENSOR_INSTANCE, spec.version))
    if rows:
        await storage.put_observations_bulk(rows)
        result.observations_written += len(rows)
    result.actors_processed += 1


async def run_circadian_backfill(
    storage: BaseRepository,
    *,
    actor_id: UUID | None = None,
    all_actors: bool = False,
    force: bool = False,
    batch: int = 500,
) -> BackfillResult:
    """Backfill circadian.* observations. Either one ``actor_id`` or ``all_actors``."""
    if actor_id is None and not all_actors:
        raise ValueError("pass actor_id=<uuid> or all_actors=True")

    result = BackfillResult()

    if actor_id is not None:
        await _backfill_actor(storage, actor_id, force=force, result=result)
        return result

    offset = 0
    while True:
        page = await storage.list_actors(
            limit=batch, offset=offset, min_messages=1, sort="handle"
        )
        if not page:
            break
        for entry in page:
            # list_actors yields (ActorTable, msg_count, obs_count) tuples, type-erased.
            actor = cast("tuple[Any, ...]", entry)[0]
            aid = cast("UUID", actor.id)
            await _backfill_actor(storage, aid, force=force, result=result)
        _log.info(
            "circadian.backfill.progress",
            processed=result.actors_processed,
            skipped=result.actors_skipped,
            observations=result.observations_written,
        )
        offset += batch

    return result
