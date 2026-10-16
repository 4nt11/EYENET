# GLINER-DOC.md: message entity extraction (who / what / when)

Status: design, pending greenlight. Grounded in the PoC under
`development/poc-gliner/` (see `FINDINGS.md`). This doc is the production shape;
the PoC is the evidence it rests on.

The global CLAUDE.md storage and service rules apply in full. Nothing here
overrides section 2 (storage abstraction), section 4 (production conventions), or
section 5 (locale).

---

## 1. Scope, from the PoC (not negotiable without new evidence)

The PoC measured GLiNER and gazetteers on 2000 real forum + 500 telegram
messages. What survived:

| entity | extractor | why |
|---|---|---|
| breached org / victim | GLiNER, ONE open-set label | open set, no finite list, ~80%+ precision zero-shot, high value |
| threat group | gazetteer (MITRE ATT&CK) | closed set; catalogued crews are precise (ShinyHunters) |
| malware | DROPPED | corpus does not name malware (proven three ways); any real dictionary floods false positives |
| wallets / CVE / onion / handle | existing regex / structured fields | deterministic, already covered, never a model |

GLiNER runs with exactly one label: `breached company or organization`. Adding
labels reintroduces the label-competition noise the PoC killed. Do not widen the
label set without a fresh calibration run.

Non-goals for v1: malware extraction, forum-native crew discovery (no external
catalog has those names; needs corpus-mining, a separate later effort),
alias/handle extraction from prose (structured fields do it better).

---

## 2. Data model

Mirrors the proven provenance idiom: `GroupCandidate` + `GroupCandidateMention`
(MODELS.md 2.20 / 2.21) and `InfrastructureArtifact` (2.24). One canonical-entity
table, one append-only mention table. This is NOT a generic graph node table and
does NOT touch `InfrastructureArtifact` (different entity class, different
resolution semantics).

New Alembic revision (section 2 of CLAUDE.md: Alembic is the source of truth, no
`create_all`).

### 2.1 `ExtractedEntity`

Canonical, deduplicated entity. One row per normalized name per kind.

| field | type | note |
|---|---|---|
| `id` | UUIDv7 PK | |
| `kind` | enum `breached_org`, `threat_group` | the surviving two classes |
| `normalized_name` | str | casefold + whitespace-collapsed match key |
| `display_name` | str | best-surface form seen (longest / titlecased) |
| `first_seen_at_source` | datetime | min over mentions |
| `last_seen_at_source` | datetime | max over mentions |
| `mention_count` | int | denormalized, recomputed on mention insert |
| `distinct_actor_count` | int | denormalized, the "who" cardinality |

Partial UNIQUE index on `(kind, normalized_name)` (raw DDL, applied by the
baseline / revision and excluded from autogenerate per the `_RAW_DDL_OBJECTS`
filter, same as the existing partial UNIQUE index).

### 2.2 `EntityMention`

One row per extraction hit. The provenance trail. Append-only. This is the
substrate for who / what / when.

| field | type | note |
|---|---|---|
| `id` | UUIDv7 PK | |
| `entity_id` | FK ExtractedEntity | |
| `message_id` | FK Message | the "when" and the evidence |
| `actor_id` | FK Actor | the "who" |
| `source_id` | FK Source | |
| `extractor` | enum `gliner`, `gazetteer` | provenance of the match |
| `label` | str | the extractor label that fired |
| `surface_text` | str | exact span as it appeared (operator-grade: keep the raw form) |
| `score` | float \| None | GLiNER confidence; null for gazetteer (deterministic) |
| `char_start` / `char_end` | int \| None | span offsets into the body, for highlight |
| `mentioned_at_source` | datetime | copied from Message for index locality |
| `mentioned_at_ingest` | datetime | |

Indexes:
- `(entity_id, mentioned_at_source DESC)`: entity timeline.
- `(actor_id, mentioned_at_source DESC)`: "what did this actor name, when."
- `(message_id)`: per-message entity list for the UI.

Operator-grade (CLAUDE.md section on evidence): we store the surface span and the
message link, we never redact. The audit log records the extraction write.

---

## 3. Storage methods (flat, on BaseRepository)

Naming per CLAUDE.md 2.4 (`<verb>_<domain>`). Declared on `BaseRepository`,
implemented in the `sqlmodel_repo/` mixin, NO dialect-specific SQL in the mixin
(Rule 1). The canonical-entity upsert is race-prone, so it follows the override
pattern: `raise NotImplementedError` on `SQLModelRepository`, SQLite
`INSERT ... ON CONFLICT DO UPDATE` override on `SQLiteRepository` (same as
`set_cursors_bulk`).

- `upsert_extracted_entity(kind, normalized_name, display_name) -> UUID`
  (override: SQLite dialect upsert on the partial UNIQUE index)
- `put_entity_mentions_bulk(rows) -> None` (one session, hot-path write)
- `recount_entity_aggregates(entity_ids) -> None` (refresh mention_count /
  distinct_actor_count / first/last seen; batch)
- `entity_timeline(entity_id, limit) -> list[EntityMention]`
- `entities_for_actor(actor_id, limit) -> list[(ExtractedEntity, count, first, last)]`
- `entities_for_message(message_id) -> list[EntityMention]`
- `top_entities(kind, since, limit) -> list[(ExtractedEntity, count)]`

Bulk helpers exist because extraction is a hot loop (CLAUDE.md 2.8). Measure
before adding more. Tests type against `BaseRepository` via `get_repository()`;
the SQLite upsert race behavior gets an impl-probe test with the `_sqlite` suffix
(Rule 2).

---

## 4. The extractor service

Deployment mirrors the incident classifier (`eyenet/classifier/`): torch is a
DELIBERATELY optional, lazy-imported dependency; only this worker imports it; the
API and every other service stay torch-free. GPU strongly preferred (the PoC ran
2000 messages in seconds on an RTX 5060, minutes on CPU).

Lives at `eyenet/sensor/entity_extractor.py` (it is a sensor: message in,
observation out), plural from day one (CLAUDE.md 4.6), `ServiceBase` subclass
(4.4), subscribes to the same message stream the stylometric sensor and
classifier consume. `attach_from_headers` inside the `create_task` body (4.5).

### 4.1 Two passes per message

1. GLiNER pass (open set): one label, `breached company or organization`. Lazy
   model load (`urchade/gliner_multi-v2.1`, multilingual, locale path first per
   CLAUDE.md section 5). Batched inference. Confidence threshold configurable,
   default 0.5 (PoC value, re-tune per calibration).
2. Gazetteer pass (closed set): compiled word-boundary regex from the ATT&CK
   group list (`development/poc-gliner/build_gazetteer.py`, keyless ATT&CK-only
   build). Deterministic, no score, cheap, in-process.

Both passes write `EntityMention` rows through `put_entity_mentions_bulk` and
upsert the canonical `ExtractedEntity`, then emit an audit event.

### 4.2 The 384-token cap (load-bearing)

GLiNER's processor truncates input at ~384 tokens. Long forum threads lose their
tail. Production MUST sliding-window chunk: split the body into overlapping
windows (approx 350 tokens, approx 50 overlap), run each, then merge spans back
to absolute char offsets and dedupe entities that straddle a boundary. The PoC
skipped this (short-message corpus); production cannot.

### 4.3 Gazetteer refresh

`build_gazetteer.py` is a periodic job, not a hot-path call. Ship a committed
`gazetteer.json` snapshot; refresh on a schedule (ATT&CK changes slowly). The
`ABUSE_CH_APIKEY` ThreatFox path stays in the builder but OFF by default: the PoC
showed it floods malware false positives on this corpus, and malware is out of
scope. Keep the code, do not wire the key into the service.

---

## 5. Bus flow and backfill

### 5.1 Streaming

New messages already fan out on the bus to the stylometric sensor and the
classifier. The extractor subscribes alongside them. Per-message latency is
dominated by GLiNER; batch across the subscription window where the bus allows,
same mitigation as the StylometricSensor dispatch (CLAUDE.md 2.8).

### 5.2 Backfill

One-shot, resumable, GPU. Follows `eyenet/sensor/backfill.py`. Cursor-based over
`Message` ordered by UUIDv7 (time-ordered PK), so a crash resumes from the last
committed message id. The corpus is approx 500k messages; at PoC throughput this
is hours on one GPU, not a distributed job. Do NOT build Spark.

Backfill writes through the same bulk storage methods. Run it against a
VACUUM INTO copy first if validating, never the live -wal (CLAUDE.md memory rule
`never_operate_live_wal_db_in_place`).

---

## 6. Calibration (per CLAUDE.md section 5, the M5 / Rutify discipline)

Precision is per-label, per-language, measured on a labeled sample, not taken
from a paper. The PoC's `extract.py` already emits a `review.txt` manual-tally
sheet; promote that into the calibration loop:

- Hold a labeled breached-org sample per calibrated language (Spanish first, then
  English, since most Spanish actors also post in English).
- Gate: breached-org precision clears the agreed floor before the sensor's output
  is trusted downstream. If a language misses the floor, disable GLiNER for that
  language (same posture as the Spanish simhashes in M6.5) and fall back to the
  gazetteer-only signal.
- Threshold and the heavier `knowledgator` model are tuning knobs deferred until
  a calibration run shows breached-org needs them. The PoC cleared the bar at
  defaults, so start there.

---

## 7. What this reuses vs adds

Reuses: `ServiceBase`, the bus subscription pattern, the message stream, the
storage factory + mixin layering, the Alembic migration flow, the backfill
cursor pattern, the audit emitter, the provenance-table idiom from
`GroupCandidateMention` / `InfrastructureArtifact`, the torch-optional worker
posture from the classifier.

Adds: two tables (`ExtractedEntity`, `EntityMention`), one Alembic revision, one
sensor (`entity_extractor.py`), the storage methods in section 3, sliding-window
chunking, and `gliner` as a worker-only optional dependency (same tier as torch).

## 8. Build order

1. Alembic revision + the two models + storage methods + impl-probe tests.
2. Sliding-window chunker + GLiNER pass (unit-tested on fixtures, no live model
   in unit tests).
3. Gazetteer pass + committed snapshot + refresh job.
4. Sensor wiring (bus subscribe, audit, plural) + integration test via the seed
   helper.
5. Backfill job.
6. Calibration sample + precision gate.
7. API read surface (who / what / when) + FE panel, once the data layer is proven.

Steps 1 to 4 are the data layer; do not build the API surface before it is green.
