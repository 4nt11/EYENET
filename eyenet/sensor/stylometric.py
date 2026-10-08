"""`StylometricSensor` — runs the four M2 stylometric/lexical primitives.

Subscribes to `raw.message.>` (queue group `sensor`), resolves actor_key →
actor_id, derefs evidence_ref from MessageStore, runs each primitive over the
per-actor corpus window, persists ObservationRows, publishes to the bus.

PLAN §8.3 failure isolation: a broken primitive marks its span errored and
skips, but NEVER aborts its siblings.
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

import structlog
from behave_text.spec import PRIMITIVE_REGISTRY, ValueTypeSpec
from opentelemetry import trace

from eyenet.contracts.enums import ValueKind
from eyenet.contracts.observation import ObservationEnvelope, ObservationRow
from eyenet.contracts.raw_message import RawMessageEnvelope
from eyenet.contracts.sensor import SensorBase
from eyenet.sensor.primitives import PRIMITIVES, PrimitiveSpec
from eyenet.service import ServiceBase
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.propagation import attach_from_headers

_tracer = trace.get_tracer("eyenet.sensor.stylometric")
_log = structlog.get_logger()

_SENSOR_INSTANCE = "stylometric_default"
_RETRY_DELAY = 0.05  # seconds to wait on actor-not-yet-ingested race

# Cursor sentinels for primitives that need the full per-actor history
# (e.g. meta.*). Mirror the values produced by SQLiteCursorStore.get() when
# no cursor row exists — see `eyenet/storage/cursors.py`.
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_NULL_UUID = UUID("00000000-0000-0000-0000-000000000000")

# Per-actor full-corpus cache (Layer 1): the full-corpus primitives used to re-fetch
# and re-decrypt an actor's ENTIRE history from the DB every dispatch (O(corpus) I/O)
# and re-tokenize it (O(corpus) CPU). We instead keep the corpus tuples per actor and,
# each dispatch, fetch only the delta since the high-water mark. Incremental primitives
# (Layer 2) additionally fold that delta into cached per-actor state so they never
# re-chew history. LRU-bounded by actor count; an evicted actor just does one cold
# reload. Process-local (rebuilds after a restart). KNOWN BOUND: a late body EDIT to an
# already-folded message won't retro-update the fold — rare (edits are uncommon, retain-
# only store), self-heals on eviction/restart, and a single message is negligible in a
# cumulative-vocabulary aggregate.
_CORPUS_CACHE_MAX_ACTORS = 512


@dataclass
class _ActorCorpusCache:
    corpus: list[tuple[datetime, UUID, str]] = field(default_factory=list)
    last_ts: datetime = _EPOCH
    last_msg_id: UUID = _NULL_UUID
    # primitive name -> its folded state (opaque; owned by the primitive's fold/finalize)
    fold_state: dict[str, Any] = field(default_factory=dict)


class StylometricSensor(ServiceBase, SensorBase):
    """Stylometric sensor running the 4 M2 primitives."""

    # Copypasta gate (anti-spam §A): a cached set of flagged template fingerprints,
    # refreshed lazily. Templated spam (identical ad text) is not authorship signal,
    # so a message whose body matches a flagged template is skipped — it never
    # pollutes an actor's writing-style profile. The set only grows as the batch
    # detector runs, so a stale cache under-gates (safe), never over-gates.
    _COPYPASTA_TTL_S = 300.0

    def _copypasta_state(self) -> tuple[frozenset[str], float]:
        # Lazy init without an __init__ override (keeps the ServiceBase ctor intact).
        return getattr(self, "_copypasta_fps", frozenset()), getattr(self, "_copypasta_at", 0.0)

    async def _is_copypasta(self, body: str) -> bool:
        from eyenet.linker.copypasta import template_fingerprint  # noqa: PLC0415

        fps, loaded_at = self._copypasta_state()
        now = time.monotonic()
        if now - loaded_at >= self._COPYPASTA_TTL_S:
            fps = frozenset(await self._storage.flagged_copypasta_fingerprints())
            self._copypasta_fps = fps
            self._copypasta_at = now
        return template_fingerprint(body) in fps

    @property
    def name(self) -> str:
        return "sensor"

    @property
    def instance_id(self) -> str:
        return _SENSOR_INSTANCE

    def primitives(self) -> Iterable[tuple[str, ValueTypeSpec]]:
        return [
            (p.name, PRIMITIVE_REGISTRY[p.name]) for p in PRIMITIVES if p.name in PRIMITIVE_REGISTRY
        ]

    async def on_subscribe(self) -> None:
        async def _handler(_subject: str, payload: bytes, headers: dict[str, str]) -> None:
            try:
                env = RawMessageEnvelope.model_validate_json(payload)
            except Exception as exc:
                _log.error("sensor.envelope_parse_error", error=str(exc))
                return
            # Fire-and-forget: don't block the bus fanout waiting for full primitive compute.
            asyncio.create_task(self._dispatch(env, headers))  # noqa: RUF006

        await self._bus.subscribe("raw.message.>", _handler, queue_group="sensor")

    async def on_raw_message(self, _envelope: RawMessageEnvelope) -> Iterable[ObservationEnvelope]:
        # SensorBase contract; StylometricSensor uses the internal _process path.
        return []

    async def _dispatch(self, env: RawMessageEnvelope, headers: dict[str, str]) -> None:
        """Bus-delivery trampoline: attach upstream trace context, then process.

        Trace context attach lives INSIDE the create_task target — see
        ``attach_from_headers`` docstring for why scheduling-time attachment
        would be a no-op.
        """

        with attach_from_headers(headers):
            await self._process(env)

    async def _process(self, env: RawMessageEnvelope) -> None:
        actor_id = await self._storage.resolve_actor_id(env.actor_key)

        if actor_id is None:
            # Race: collector may not have committed the actor row yet.
            await asyncio.sleep(_RETRY_DELAY)
            actor_id = await self._storage.resolve_actor_id(env.actor_key)
            if actor_id is None:
                _log.warning(
                    "sensor.actor_not_found",
                    actor_key=env.actor_key,
                    evidence_ref=env.evidence_ref,
                )
                return

        body_bytes = await self._storage.get_message_body(env.evidence_ref)
        if body_bytes is None:
            _log.warning("sensor.body_not_found", evidence_ref=env.evidence_ref)
            return

        await self.audit.emit(
            event="evidence_access",
            subject_kind="evidence",
            payload={
                "evidence_ref": env.evidence_ref,
                "actor_id": str(actor_id),
                "reason": "stylometric_sensor_primitive_compute",
            },
        )

        body = body_bytes.decode("utf-8")
        # Anti-spam §A: templated spam is not authorship signal — skip it so it
        # never enters the actor's stylometric profile (that is what produced the
        # false "same author" clusters over copypasta ad text).
        if await self._is_copypasta(body):
            _log.debug("sensor.copypasta_skipped", evidence_ref=env.evidence_ref)
            return

        with _tracer.start_as_current_span(
            "sensor.dispatch",
            attributes={
                "service.name": self.name,
                "service.instance_id": self.instance_id,
                "actor.id": str(actor_id),
                "message.evidence_ref": env.evidence_ref,
                "sensor.primitive_count": len(PRIMITIVES),
            },
        ):
            await self._run_primitives(actor_id, env, body)

    def _corpus_cache_dict(self) -> OrderedDict[UUID, _ActorCorpusCache]:
        # Lazy init without an __init__ override (mirrors _copypasta_state).
        cache: OrderedDict[UUID, _ActorCorpusCache] | None = getattr(
            self, "_corpus_cache_map", None
        )
        if cache is None:
            cache = OrderedDict()
            self._corpus_cache_map = cache
        return cache

    async def _load_full_corpus_incremental(
        self, actor_id: UUID
    ) -> tuple[_ActorCorpusCache, list[tuple[datetime, UUID, str]]]:
        """Return the actor's cached full corpus + the delta fetched this dispatch.

        Cold entry: fetch the whole history (and the delta IS the whole history).
        Warm entry: fetch only rows after the high-water mark and append. LRU-bounded.
        """
        cache = self._corpus_cache_dict()
        entry = cache.get(actor_id)
        if entry is None:
            entry = _ActorCorpusCache()
            delta = await self._storage.iter_corpus_since(actor_id, _EPOCH, _NULL_UUID)
        else:
            delta = await self._storage.iter_corpus_since(
                actor_id, entry.last_ts, entry.last_msg_id
            )
        if delta:
            entry.corpus.extend(delta)
            last_ts, last_mid, _ = delta[-1]
            entry.last_ts, entry.last_msg_id = last_ts, last_mid
        cache[actor_id] = entry
        cache.move_to_end(actor_id)
        while len(cache) > _CORPUS_CACHE_MAX_ACTORS:
            cache.popitem(last=False)
        return entry, delta

    async def _run_primitives(self, actor_id: UUID, env: RawMessageEnvelope, _body: str) -> None:
        _cursor_names = [s.name for s in PRIMITIVES if not s.requires_full_corpus]
        _cursor_cache = await self._storage.get_cursors_bulk(actor_id, _cursor_names)

        # Resolve current-evidence_ref → msg_id once for the dispatch.
        # Every primitive that succeeds advances its cursor to this point;
        # batching this one lookup saves a session per primitive.
        _current_msg_id = await self._storage.get_message_id_by_evidence_ref(env.evidence_ref)
        if _current_msg_id is None:
            from eyenet.models._base import new_uuid7  # noqa: PLC0415

            _current_msg_id = new_uuid7()

        _cursor_updates: list[tuple[str, datetime, UUID]] = []
        _observation_rows: list[ObservationRow] = []
        succeeded = failed = 0

        # Layer 1: load the per-actor full corpus incrementally (delta-only fetch),
        # shared by every full-corpus primitive. Fetch the delta's bodies once iff an
        # incremental body-reading primitive (dialect_region) will fold them.
        _entry: _ActorCorpusCache | None = None
        _delta: list[tuple[datetime, UUID, str]] = []
        _delta_bodies: dict[str, str] = {}
        # One-element box so the lazy non-incremental full-body fetch is memoized across
        # the primitive loop without inflating _run_primitives' branch/statement count.
        _full_bodies_box: list[dict[str, str] | None] = [None]
        if any(s.requires_full_corpus for s in PRIMITIVES):
            _entry, _delta = await self._load_full_corpus_incremental(actor_id)
            if _delta and any(s.supports_incremental and s.requires_bodies for s in PRIMITIVES):
                _delta_bodies = await _batch_fetch_bodies(self._storage, _delta)

        # Follow-up: the (non-reply) window primitives share one since-cursor fetch per
        # distinct cursor instead of each doing its own corpus+bodies round-trips. In
        # steady state every window primitive sits at the same cursor, so this is one
        # fetch for all of them instead of N.
        _window_cache = await self._prefetch_window_fetches(actor_id, _cursor_cache)

        for spec in PRIMITIVES:
            span_name = f"sensor.primitive.{spec.name.replace('.', '.')}"
            with _tracer.start_as_current_span(
                span_name,
                attributes={
                    "primitive.name": spec.name,
                    "primitive.version": spec.version,
                    "primitive.namespace": spec.name.split(".")[0],
                },
            ) as span:
                try:
                    t0 = time.monotonic()
                    obs = await self._dispatch_primitive(
                        spec,
                        actor_id,
                        env,
                        entry=_entry,
                        delta=_delta,
                        delta_bodies=_delta_bodies,
                        cursor=_cursor_cache.get(spec.name),
                        full_bodies_box=_full_bodies_box,
                        window_cache=_window_cache,
                    )
                    duration_ms = (time.monotonic() - t0) * 1000
                    span.set_attribute("primitive.duration_ms", duration_ms)

                    if obs is None:
                        span.set_attribute("primitive.outcome", "skipped")
                        span.set_attribute("primitive.skip_reason", "corpus_too_short")
                        _log.debug(
                            "primitive.skipped",
                            primitive=spec.name,
                            actor_id=str(actor_id),
                        )
                    else:
                        span.set_attribute("primitive.outcome", "ok")
                        span.set_attribute("primitive.value", str(obs.value)[:120])

                        await self.publisher.publish_observation(obs)

                        row = _observation_to_row(obs, actor_id, self.instance_id, spec.version)
                        _observation_rows.append(row)

                        _cursor_updates.append((spec.name, env.sent_at_source, _current_msg_id))

                        succeeded += 1
                except Exception as exc:
                    failed += 1
                    span.set_attribute("primitive.outcome", "error")
                    span.record_exception(exc)
                    _log.error(
                        "primitive.error",
                        primitive=spec.name,
                        actor_id=str(actor_id),
                        error=str(exc),
                    )

        if _observation_rows:
            await self._storage.put_observations_bulk(cast("list[object]", _observation_rows))
        if _cursor_updates:
            await self._storage.set_cursors_bulk(actor_id, _cursor_updates)

        _log.info(
            "sensor.dispatch.complete",
            actor_id=str(actor_id),
            evidence_ref=env.evidence_ref,
            succeeded=succeeded,
            failed=failed,
        )

    async def _prefetch_window_fetches(
        self, actor_id: UUID, cursor_cache: dict[str, tuple[datetime, UUID]]
    ) -> dict[tuple[datetime, UUID], tuple[list[tuple[datetime, UUID, str]], dict[str, str]]]:
        """Fetch each distinct since-cursor window (corpus + bodies) ONCE for the whole
        dispatch, so the non-reply window primitives share it instead of each hitting the
        DB. Keyed by resolved cursor; a missing cursor defaults to (epoch, null) exactly
        like the per-primitive path would. Reply + full-corpus primitives are excluded
        (they have their own fetch shapes)."""
        needs_bodies: dict[tuple[datetime, UUID], bool] = {}
        for spec in PRIMITIVES:
            if spec.requires_full_corpus or spec.requires_reply_corpus:
                continue
            cur = cursor_cache.get(spec.name) or (_EPOCH, _NULL_UUID)
            needs_bodies[cur] = needs_bodies.get(cur, False) or spec.requires_bodies
        out: dict[
            tuple[datetime, UUID], tuple[list[tuple[datetime, UUID, str]], dict[str, str]]
        ] = {}
        for (since_ts, since_mid), want_bodies in needs_bodies.items():
            corpus = await self._storage.iter_corpus_since(actor_id, since_ts, since_mid)
            bodies = (
                await _batch_fetch_bodies(self._storage, corpus) if want_bodies and corpus else {}
            )
            out[(since_ts, since_mid)] = (corpus, bodies)
        return out

    async def _dispatch_primitive(
        self,
        spec: PrimitiveSpec,
        actor_id: UUID,
        env: RawMessageEnvelope,
        *,
        entry: _ActorCorpusCache | None,
        delta: list[tuple[datetime, UUID, str]],
        delta_bodies: dict[str, str],
        cursor: tuple[datetime, UUID] | None,
        full_bodies_box: list[dict[str, str] | None],
        window_cache: dict[
            tuple[datetime, UUID], tuple[list[tuple[datetime, UUID, str]], dict[str, str]]
        ],
    ) -> ObservationEnvelope | None:
        """Route one primitive to the right path: incremental fold, cached full-corpus
        recompute, or since-cursor window. Extracted from the dispatch loop to keep it
        under the branch/statement budget."""
        fold_fn, finalize_fn = spec.fold, spec.finalize
        if (
            spec.requires_full_corpus
            and fold_fn is not None
            and finalize_fn is not None
            and entry is not None
        ):
            # Layer 2: fold ONLY the delta into cached per-actor state, then finalize.
            # Bit-identical to a full recompute (see the equivalence test).
            bodies_delta = delta_bodies if spec.requires_bodies else {}
            state = fold_fn(entry.fold_state.get(spec.name), delta, bodies_delta)
            entry.fold_state[spec.name] = state
            obs: ObservationEnvelope | None = finalize_fn(state)
            return obs
        if spec.requires_full_corpus and entry is not None:
            # Non-incremental full-corpus (meta.*): recompute over the cached corpus —
            # no DB re-fetch. Bodies fetched once (lazily) only if the primitive needs them.
            if spec.requires_bodies and full_bodies_box[0] is None:
                full_bodies_box[0] = await _batch_fetch_bodies(self._storage, entry.corpus)
            return await self._compute_primitive(
                spec,
                actor_id,
                env,
                _precomputed_corpus=entry.corpus,
                _precomputed_bodies=full_bodies_box[0] if spec.requires_bodies else None,
            )
        # Reply-graph window primitive: its own fetch shape (iter_corpus_since_with_reply).
        if spec.requires_reply_corpus:
            return await self._compute_primitive(spec, actor_id, env, _cursor=cursor)
        # Window primitive: serve from the shared per-cursor prefetch (no own DB round-trip).
        corpus, bodies = window_cache.get(cursor or (_EPOCH, _NULL_UUID), ([], {}))
        if not corpus:
            return None
        return spec.compute(corpus=corpus, bodies=bodies if spec.requires_bodies else {})

    async def _compute_primitive(
        self,
        spec: PrimitiveSpec,
        actor_id: UUID,
        _env: RawMessageEnvelope,
        *,
        _precomputed_corpus: list[tuple[datetime, UUID, str]] | None = None,
        _precomputed_bodies: dict[str, str] | None = None,
        _cursor: tuple[datetime, UUID] | None = None,
    ) -> ObservationEnvelope | None:
        # Meta primitives need the actor's full history, not the
        # since-cursor delta — override with epoch sentinels.
        if spec.requires_full_corpus:
            since_ts, since_msg_id = _EPOCH, _NULL_UUID
        elif _cursor is not None:
            since_ts, since_msg_id = _cursor
        else:
            since_ts, since_msg_id = await self._storage.get_cursor(actor_id, spec.name)

        if spec.requires_reply_corpus and spec.compute_with_reply is not None:
            corpus_reply = await self._storage.iter_corpus_since_with_reply(
                actor_id, since_ts, since_msg_id
            )
            if not corpus_reply:
                return None
            return await spec.compute_with_reply(corpus_with_reply=corpus_reply)

        if _precomputed_corpus is not None:
            corpus = _precomputed_corpus
        else:
            corpus = await self._storage.iter_corpus_since(actor_id, since_ts, since_msg_id)
        if not corpus:
            return None

        bodies: dict[str, str]
        if not spec.requires_bodies:
            bodies = {}
        elif _precomputed_bodies is not None:
            bodies = _precomputed_bodies
        else:
            bodies = await _batch_fetch_bodies(self._storage, corpus)

        return spec.compute(corpus=corpus, bodies=bodies)


async def _batch_fetch_bodies(
    storage: BaseRepository,
    corpus: list[tuple[datetime, UUID, str]],
) -> dict[str, str]:
    bodies: dict[str, str] = {}
    for _ts, _mid, ref in corpus:
        b = await storage.get_message_body(ref)
        if b is not None:
            bodies[ref] = b.decode("utf-8")
    return bodies


def _observation_to_row(
    obs: ObservationEnvelope,
    actor_id: UUID,
    sensor_instance: str,
    primitive_version: str = "0",
) -> ObservationRow:
    """Map a BEHAVE-TEXT Observation to an EYENET ObservationRow."""

    parts = obs.primitive.split(".")
    namespace = parts[0] if parts else obs.primitive

    value = obs.value
    value_hash: str | None = None
    value_numeric: float | None = None
    value_enum: str | None = None
    value_array: list[str] | None = None
    value_array_numeric: list[float] | None = None

    if isinstance(value, str):
        value_hash = value
        vkind = ValueKind.HASH
    elif isinstance(value, float | int) and not isinstance(value, bool):
        value_numeric = float(value)
        vkind = ValueKind.NUMERIC
    elif isinstance(value, list):
        if value and isinstance(value[0], str):
            value_array = value
            vkind = ValueKind.ARRAY_STR
        else:
            value_array_numeric = [float(v) for v in value]
            vkind = ValueKind.ARRAY_NUMERIC
    else:
        value_enum = str(value)
        vkind = ValueKind.ENUM_STR

    window_start: datetime | None = None
    window_end: datetime | None = None
    if obs.window:
        window_start = datetime.fromtimestamp(obs.window.start_ts, tz=UTC)
        window_end = datetime.fromtimestamp(obs.window.end_ts, tz=UTC)

    return ObservationRow(
        actor_id=actor_id,
        evidence_ref=obs.evidence_ref,
        primitive_namespace=namespace,
        primitive_name=obs.primitive,
        primitive_version=primitive_version,
        value_kind=vkind,
        value_hash=value_hash,
        value_numeric=value_numeric,
        value_enum=value_enum,
        value_array=value_array,
        value_array_numeric=value_array_numeric,
        window_start=window_start,
        window_end=window_end,
        observed_at=datetime.now(tz=UTC),
        sensor_instance=sensor_instance,
    )


__all__ = ["StylometricSensor"]
