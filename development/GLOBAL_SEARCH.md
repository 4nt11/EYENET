# GLOBAL_SEARCH.md — unified cross-entity search ("global query")

Status: DESIGN. Phase 1 approved to start. Author target: operator-facing
investigation UX.

## As-built (Phase 1, SQLite path) — read this first

What SHIPPED in the `phase1-global-search` work (deviations from the design
below are deliberate and were decided with the operator):

- **Store placement:** `search_document` lives in the **main store**, NOT a
  separate `search.db`/schema. Only `main`/`audit` stores exist and a third
  store is large, nonexistent plumbing; `message_fts` proves in-main FTS +
  in-place rebuild. (So §2.4's "own search.db / schema" is NOT what shipped.)
- **SQLite FTS:** two FTS5 externalcontent tables — `search_fts_prose`
  (unicode61, diacritics folded) + `search_fts_handles` (trigram, substring).
  FTS5 tokenizer is table-level, hence two tables (correcting §3's "one table,
  two tokenizers"). Migration `0006_search_document`.
- **API:** `GET /v1/search` with `types`/`status`/`source` + `by_type`/
  `by_source` facets, `read:search` scope. Documented in the OpenAPI contract.
- **FE:** global box in `TopBar` (+`/` focus) + `/search` grouped results.
- **Population:** a read-only one-shot **backfill** (`eyenet search-backfill`)
  covers actor/group/message/persona/case/document/artifact/crew. Bootstraps the
  index; re-run any time to rebuild.
- **Live freshness:** the **`SearchIndexer` bus service** (`eyenet
  search-indexer`, a `ServiceBase`) subscribes to `entity.>`, `raw.message.>`,
  `attribution.persona.updated`, `classify.document.uploaded` and reindexes the
  one named entity via the shared `haystack.py` builders.
- **Events:** new `entity.<type>.changed` subjects. `upsert_actor`/`upsert_group`
  return `(id, search_changed)`; collectors + discovery sensor emit **only on real
  change** (new row or handle/title differs), so a busy group/actor does NOT
  re-emit per message (the change-gated design — avoids 3x ingest-bus write
  amplification). Case create/update/close/archive/reopen + the operator crew-case
  path emit `entity.case.changed`.

**Still deferred:**

- **Postgres FTS** (`tsvector`/GIN/`pg_trgm`, §2.2): the PG backend serves search
  via the generic ANSI `LIKE` fallback (the table is created by the PG baseline
  since it is in `_MAIN_TABLES`). The FTS optimization is unwritten; the live
  stack is SQLite so it is not on the critical path.
- **Group joined/monitored status on join/leave:** the status facet is set at
  index time from membership; a group becomes searchable via its message stream,
  but a pure join/leave with no message does not yet re-emit (the crew auto-sweep
  case-create likewise relies on the backfill). Minor facet staleness, Phase 3.
- **Attachment indexing** as its own entity (documents are covered).
- **Phase 1.5 query DSL** (§9) and **Phase 2** (graph pivot, create-case-from-
  query) remain as designed below.

Supersedes the scattered per-entity search surface
(`search_actors`, `search_messages_in_category`, `/v1/graph/search`), which it
absorbs over time rather than deleting on day one.

This builds on the M9 storage abstraction (CLAUDE.md §2): factory dispatch, flat
`BaseRepository`, dialect SQL fenced into the concrete backend. The new search
seam follows the exact pattern already set by `_body_match`. Postgres is the
primary engine (the backend is live); SQLite stays the dev/test/small-operator
default and MUST implement the same contract.

---

## 0. Why (so future-you does not relitigate it)

Two problems, one feature.

1. **The current search is per-field and useless.** `search_messages_in_category`
   runs FTS over `message.body` ALONE. Not the thread title, not the author
   handle, not source, not metadata. `search_actors` hits handle + display name
   only. There is no way to type one string and ask "where does this appear,
   anywhere." The operator (you) has been grepping the DB by hand. That is the
   actual failure state this fixes.

2. **No cross-entity view.** An investigation starts from a token (`zfo`,
   `t.me/zfoleaks`, a wallet, a university name) and wants back EVERYTHING that
   token touches: actors, groups, threads, posts, mentions, artifacts, personas.
   Today that is N separate queries the UI does not even make.

**Non-goal: Elasticsearch.** It violates small-operator scope (a JVM and a
cluster to babysit for "the little guy"). Postgres FTS (`tsvector` + GIN) plus
`pg_trgm` for substring/handle matching gives the same operator experience with
zero new runtime services. SQLite FTS5 covers the dev/default path. We already
ship both engines. The "Elastic feeling" is the UX, not the daemon.

---

## 1. The core idea: one haystack per entity

The fix for problem (1) is a **denormalized search document**: one row per
searchable entity whose `haystack` concatenates EVERY searchable field that
entity owns. Index the haystack once. Stop indexing single columns.

`search_document`:

| column        | notes                                                        |
|---------------|--------------------------------------------------------------|
| `entity_type` | enum, see §1.1                                               |
| `entity_id`   | the source row's id                                          |
| `source_id`   | for the source/platform facet and access scoping            |
| `status`      | lifecycle facet within a type (group: candidate/joined/monitored/known; linkage: proposed/confirmed/...) |
| `title`       | display label for the result row (handle, thread title, ...) |
| `subtitle`    | secondary line (source kind, date, author)                   |
| `haystack`    | ALL searchable text for this entity, concatenated            |
| `handles`     | identifiers column: handles, aliases, t.me, wallets (trigram-indexed) |
| `updated_at`  | for incremental reindex + staleness                          |

`handles` is a separate column on purpose: identifiers want **substring and
fuzzy** matching (`zfo` must hit `zfoleaks`, `zfo$` must hit `zfo`), which is a
different index (trigram) from prose (tsvector/bm25). See §3.

### 1.1 Entity taxonomy (grounded in the models, not guessed)

The model set is richer than a flat type list, and two distinctions are
load-bearing.

**Indexed types and their haystack composition (the whole value lives here):**

- **actor** (`actor`): `current_handle` + `current_display_name` +
  `platform_userid` + every `actor_alias_history.value` + `notes` +
  `operator_assessment`. Handles/aliases/userid also go in `handles`.
- **group** (`group_` + `group_candidate`, unified under one type with a
  `status` facet): `current_title` + `current_description` for confirmed groups;
  `display_name_hint` for candidates. **Status is derived at index time**, NOT a
  column on `group_`:
  - `candidate`  = row lives in `group_candidate`
  - `joined`     = has an open `collector_group_membership` (left_at IS NULL)
  - `monitored`  = joined AND the owning collector is actively monitoring
  - `known`      = a `group_` row with no open membership (unjoined/unmonitored)

  This is exactly the "joined / monitored / unjoined / candidate" split you
  called out. One type, one `status` facet, so the UI filters without four
  separate result buckets.
- **thread** (`thread_summary` / forum thread aliases): thread title + OP
  message snippet + victim fields. May fold under `group` if the UI prefers;
  keep separate if forum threads deserve their own bucket.
- **message / post** (`message`): `body` + denormalized **group/thread title** +
  denormalized **author handle**. The denormalized title + author are the part
  today's `search_messages_in_category` throws away.
- **mention** (`group_candidate_mention`): mention evidence + mentioning actor
  handle + mentioned target.
- **artifact** (`infrastructure_artifact`, with its `actor_artifact` /
  `group_access_artifact` joins): `value` + `kind` + `details`. This is the
  pivot surface for `t.me/...`, wallets, domains. `value` goes in `handles`.
- **persona** (`persona`): `label` + member actor handles. Derived cross-actor
  identity.
- **crew** (`manual_crew` ONLY): `name` + `notes` + member handles. **Important:
  the derived crews on `/actor-groups` are connected components of the
  shared-infra graph, recomputed per request. They are NOT a table and are NOT
  indexable.** Only the operator-curated `manual_crew` is a search entity;
  derived crews surface through their member actors/artifacts.
- **case** (`case_v2`): `title` + `description`. Access-scoped per case
  membership (§7).
- **document** (`document`): `filename` + **`extracted_text`** (the full
  operator-grade extracted body). This is a large, high-value haystack my first
  draft missed entirely.
- **attachment** (`attachment`): filename + caption/evidence (confirm exact
  columns at build; the model lives outside `models/attachment.py`).
- **incident** (`incident`): low-text. It is per-message multi-label
  classification (`labels` JSON + scores), not prose. Index the fired `labels`
  (+ `incident_rule` name) as a facet and link back to the message; do not treat
  it as a title/body entity.

**Deliberately NOT indexed (not investigation targets, or sensitive):**

- **identity** (operator sock-puppets): operator infrastructure. Exclude from
  default search; expose only behind an admin-scoped facet if ever wanted.
- **source / collector / system_user / audit / observation / reaction**: infra
  and non-text telemetry. Not search targets.
- **linkage**: a relationship, not a text entity. It surfaces through the two
  actors it connects. Optional later: index the pair's handles so a handle
  search can offer "linkages touching this actor," carrying a `status` facet
  (proposed/confirmed/...). Not Phase 1.

---

## 2. The storage seam

### 2.1 Contract on `BaseRepository`

One flat method, dialect-free signature, same shape as the existing paged reads:

```python
async def search_global(
    self,
    q: str,
    *,
    types: Sequence[EntityType] | None = None,   # None = all
    limit: int,
    offset: int = 0,
    source_id: UUID | None = None,               # platform facet
) -> list[SearchHit]: ...

async def count_search_global(self, q: str, *, types=..., source_id=...) -> int: ...
```

`SearchHit` is a backend-neutral dataclass: `entity_type`, `entity_id`,
`source_id`, `title`, `subtitle`, `score`, `snippet`. The API layer maps it to
the response schema. No ORM rows leak across the boundary.

The per-entity methods (`search_actors`, `search_messages_in_category`) stay for
now; they become thin callers of `search_global(types=[...])` in a later cleanup,
not a Phase 1 deletion.

### 2.2 Postgres implementation (primary)

Reuse the §2.5 pattern from POSTGRES_PORT.md, generalized from `message.body` to
the haystack:

- `search_document.haystack_tsv tsvector` GENERATED from `haystack`
  (`to_tsvector('simple', ...)`) plus a **GIN** index.
- `search_document.handles` plus a **GIN `pg_trgm`** index (`gin_trgm_ops`) for
  substring/handle/leet matching. `pg_trgm` is a `CREATE EXTENSION`, one line in
  the pg baseline raw DDL.
- Query: `haystack_tsv @@ websearch_to_tsquery('simple', :q)` for prose, OR
  `handles ILIKE '%'||:q||'%'` / `similarity(handles, :q)` for identifiers,
  unioned and ranked by `ts_rank` + trigram `similarity` + a per-type boost.
- `websearch_to_tsquery` neutralizes operator typos/syntax the way the SQLite
  side must guard manually.

### 2.3 SQLite implementation (dev/default)

- FTS5 virtual table over `search_document(haystack, handles)`, external-content
  against the `search_document` base table (same `content=`/`content_rowid=`
  trick `message_fts` already uses).
- **Tokenizer decision (load-bearing):** the current `message_fts` uses the
  DEFAULT tokenizer, which is why `MATCH 'zfo'` returned zero against
  `zfoleaks`. For `handles` use the **`trigram`** tokenizer (true substring); for
  `haystack` prose keep `unicode61` with `remove_diacritics 2` (Spanish corpus).
  Two columns, two tokenizers, one table.
- Rank with `bm25()` + the same per-type boost.

### 2.4 Freshness: a `SearchIndexer` service, not triggers

The haystack is cross-table (a message's haystack needs its group's title), so
single-table generated columns and FTS triggers cannot assemble it alone. The
EYENET-native answer is a **plural `SearchIndexer(ServiceBase)`** subscribing to
domain events on the bus (same shape as every other service, plural from day
one per CLAUDE.md §4.6): on actor/group/message/... upsert events it rebuilds
that entity's `search_document` row. This is the event-driven, always-fresh
answer, not a half-measure to be upgraded later.

- A **one-shot backfill** from the live corpus bootstraps the index on first
  deploy (and after any schema change to the haystack). That is a bootstrap, not
  the freshness mechanism; steady-state freshness is the indexer consuming bus
  events.
- **`search_document` is DERIVED and REBUILDABLE.** It is not the corpus. It can
  be dropped and rebuilt from the base tables at any time. So it must NOT share
  fate with the irreplaceable operating data: give it its own schema (Postgres)
  or its own `search.db` file (SQLite), so a reindex is `TRUNCATE`/`rm` plus a
  rebuild with zero risk to `main.db`. This aligns with the never-wipe-main rule
  instead of fighting it.

### 2.5 Migrations

Both trees get the `search_document` table plus its indexes as **raw DDL in the
baseline**, excluded from autogenerate via `_RAW_DDL_OBJECTS` (same fence as
`message_fts`, `vector_signature`, the partial UNIQUE index). The `pg_trgm`
extension and the FTS5 virtual table are raw DDL by nature. Never let
`--autogenerate` DROP them.

---

## 3. Ranking

One ordered result set, merged across types, ranked by:

1. **field/type boost**: exact `handles` hit beats alias hit beats title hit
   beats body mention. An actor whose handle IS the query ranks above a message
   that merely mentions it.
2. **text relevance**: `ts_rank` (PG) / `bm25` (SQLite) over the haystack.
3. **fuzzy identifier**: trigram `similarity` so `zfo`/`zfo$`/`zfoleaks` cluster.
4. **recency** tiebreak on `updated_at`.

Results are also **grouped by `entity_type`** in the response so the UI can show
"Actors (3), Threads (12), Posts (40)" with a per-group peek plus "see all."

---

## 4. API

`GET /v1/search`:

```
q        required, 1..256
types    optional CSV facet (actor,group,thread,message,mention,artifact,persona,crew,case,document,attachment,incident)
status   optional CSV facet within a type (e.g. group: candidate,joined,monitored,known)
source   optional source_id facet
cursor   opaque (deps_paging)
limit    1..100 default 25
include_total 0/1
```

Response: `CursorPageSearchHit` plus a `by_type` AND a `by_source` count map.
Reuses `CursorParams`, problem+json errors, `RequireScope("read:search")` (new
scope; maps from the existing read scopes at role config). `/v1/graph/search`
stays as a thin alias (`types=actor`) until the FE fully migrates, then
deprecate.

### 4.1 Data sources are a first-class facet

`search_document.source_id` is populated for every indexed entity, so source is
not an afterthought:

- `by_source` count map in the response (parallel to `by_type`), so the UI shows
  "darkforums (41) · raidforums (12) · telegram:... (3)".
- `source` query filter (one or CSV) to scope a search to a board/channel.
- Every result row renders its source in the subtitle. This is what makes a
  cross-source actor (the LaPampaLeaks-across-three-sources case) legible at a
  glance instead of three unrelated-looking rows.

Sources themselves (`source.display_name`) may also be indexed as a thin entity
so you can find a source by name; low priority, cheap.

## 4a. Action: create a case from a query

Turn a search into an investigation in one click: "Create case from these
results" (and "Add selected to case" for an existing one).

**This is mostly composition of endpoints that already exist**, not new
plumbing:

1. `POST /v1/cases` with a title (operator-named, defaulting to the query) and
   the query saved in `description`.
2. `POST /v1/cases/{id}/members/bulk` (already exists, caps at 500 subjects,
   takes one `add_reason`) with the selected hits mapped to
   `{subject_kind, subject_id}`; `add_reason` carries the query string (it
   satisfies the `>= 16` char minimum naturally).

**The one real gap — `CaseSubjectKind` is narrower than the search types.**
Today it is `{observation, attachment, message, actor, persona, linkage}`. Search
returns `actor, group, thread, message, mention, artifact, persona, crew, case,
document, incident`. So only actor / message / persona / attachment are addable
as-is; **group, thread, artifact, and document are not valid case subjects**, and
those are exactly the evidence an operator wants to case up (a leaked document, a
forum thread). Dropping them silently is a half-solution.

Decision (full solution): **extend `CaseSubjectKind`** to add `group`, `thread`,
`artifact`, `document`. This is a Case-subsystem change bundled with this feature,
not a search change: the enum, plus the `case_member` resolution/rendering path
that dereferences `subject_id` across stores, plus per-kind access scoping. Treat
it as a proper sub-task with its own tests, not a one-line enum edit.

**Semantics:**

- **Snapshot by default.** The hits matching at click time become members. Simple,
  predictable, no schema change beyond the enum extension. A broad query must force
  "select which / confirm bulk" so you do not dump 400 noisy messages into a case.
- **Living query (later, optional).** There is NO saved-query concept today (no
  `origin_query` field, no `saved_query` table). A case that re-runs its query to
  pull NEW hits needs one of those. Defer until the snapshot flow proves the
  workflow; then add `case_v2.origin_query` (or a small `case_saved_query` side
  table) and a "re-run and add new" action. There is prior art for idempotent
  auto-created cases in `case_v2.crew_key` to mirror.
- **Scoping + audit.** Adding from search goes through the existing audited
  member-add path (never a backdoor), and respects the same per-case access and
  per-source clearance the rest of the system enforces.

---

## 5. Frontend (Phase 1 scope)

- A **global search box** in the app shell/layout (not buried on one page),
  keyboard focusable (`/`), debounced.
- A **results view** grouped by entity type; each hit row links to its existing
  detail surface (actor, group/thread, linkage, persona). Snippet with the match
  highlighted.
- Reuse the `DataTable` + cursor "Load more" pattern just wired onto the linkages
  page, and the same server-filter plus client quick-filter ergonomics.

Out of Phase 1 FE scope: the graph viz (that is Phase 2).

---

## 6. Phasing

- **Phase 1 (this doc):** `search_document` + `search_global`/`count_search_global`
  on both backends, the `SearchIndexer` bus service to maintain it, a one-shot
  backfill from the live corpus, `GET /v1/search` with the `by_type` + `by_source`
  facets (§4.1), and the FE global box plus grouped results with source chips.
  Plain multi-term plus the engines' native AND/OR/NOT/phrase (free). Ends the
  manual DB spelunking. Ships standalone.
- **Phase 1.5 — the query DSL (§9).** The neutral query language: field scoping
  (`message.author`, `group.status`, `forum.thread.author`), `==`/`!=` exact
  predicates, boolean grouping, compiled to each backend through one AST. Built
  properly (grammar, field registry, dual compiler, injection-safe, parity
  tests), against plumbing Phase 1 already landed. Not folded into Phase 1 so the
  first usable search is not blocked on the parser.
- **Phase 2:**
  - "Pivot to graph" from a hit, rendering the EXISTING `graph_node`/`graph_edge`
    + `/v1/graph` ego-network with **Cytoscape.js** (small-operator scale) or
    **Sigma.js** (WebGL) if node counts explode. Search is the entry point; the
    graph is the exploration.
  - "Create case from a query" (§4a), including the `CaseSubjectKind` extension
    for group/thread/artifact/document.
- **Phase 3:** relevance tuning, the trigram-vs-prefix decision backed by
  MEASURED index size on the real corpus, GIN write-amplification watch
  (POSTGRES_PORT §5.3), folding the legacy per-entity searches into
  `search_global`, and (optional) the living-query case (`origin_query`).

---

## 7. Risks / things to measure, not guess

- **Index size** of a trigram index over the full handles/haystack on the real
  corpus. The corpus is large and irreplaceable; measure before committing the
  tokenizer choice.
- **GIN write amplification** on ingest (POSTGRES_PORT §5.3). The indexer path
  must NOT sit on the hot message-ingest write loop; it consumes events
  off-path. And it must emit NO audit event (same invariant that lets Postgres
  ingest scale, POSTGRES_PORT §0).
- **Reindex cost / freshness lag** window on the event-driven path.
- **Access scoping**: search must respect the same per-source/clearance scoping
  the detail endpoints enforce. A hit must never leak an entity the caller cannot
  already read. Verify at the API layer, not just the index.

---

## 8. Build order (Phase 1, worktree `phase1-global-search`)

1. `search_document` base table plus raw-DDL indexes in BOTH baselines; the
   `pg_trgm` extension; the `_RAW_DDL_OBJECTS` fence.
2. `SearchHit` contract plus `search_global`/`count_search_global` on
   `BaseRepository`; the generic mixin raises `NotImplementedError` for the
   dialect bits; implement the FTS predicate on each concrete backend (the
   `_body_match` seam, generalized).
3. `SearchIndexer` bus service (plural `ServiceBase`, consumes domain events)
   plus a one-shot corpus backfill to bootstrap the index.
4. `GET /v1/search` plus schema plus scope.
5. FE global box plus grouped results.
6. Full gate (ruff, mypy --strict, bandit, pytest including a SQLite trigram
   probe and, if a server is available, a Postgres-pinned FTS probe), then a
   `--no-ff` merge.

---

## 9. Query language (Phase 1.5)

Operator-facing query sugar. The hard rule: because we ship two backends, we do
NOT forward raw engine syntax (Postgres `websearch_to_tsquery` and SQLite FTS5
`MATCH` have different grammars; forwarding diverges behavior). We own ONE
neutral grammar, parse to a backend-neutral AST, and compile per backend.

### 9.1 Two planes

- **Text plane** (fuzzy, ranked): bare terms and `"phrases"`, matched against the
  haystack, scored. Compiles to `websearch_to_tsquery` / FTS5 `MATCH`.
- **Field plane** (exact, filtering): `field == value`, `field != value`.
  Compiles to parameterized SQL `=` / `<>` / `ILIKE`. Filters, does not rank.
- `field : text` is the hybrid: a text match scoped to one field.

### 9.2 Grammar (sketch)

```
query      := or_expr
or_expr    := and_expr (OR and_expr)*
and_expr   := factor (AND? factor)*        # adjacency = implicit AND
factor     := NOT? ( '(' or_expr ')' | predicate | term )
predicate  := FIELD ( '==' | '!=' | ':' ) value
term       := WORD | '"' PHRASE '"' | WORD '*'
```

Examples:

```
ransomware AND (group.status == monitored OR group.status == joined)
message.author == zfo
forum.thread.author != lapampaleaks AND "school database"
artifact.value : t.me   source:darkforums
```

### 9.3 Field registry (the real deliverable + the security boundary)

One registry maps every dotted field to `(entity_type, column-or-denormalized,
match_kind: text|exact)`:

| field                 | entity | column                 | kind  |
|-----------------------|--------|------------------------|-------|
| `message.content`     | message| body                   | text  |
| `message.author`      | message| denormalized handle    | exact |
| `group.title`         | group  | current_title          | text  |
| `group.status`        | group  | status facet           | exact |
| `forum.thread.author` | thread | OP author handle       | exact |
| `actor.handle`        | actor  | current_handle/aliases | exact |
| `artifact.value`      | artifact| value                 | text  |
| `case.title`          | case   | title                  | text  |
| `document.text`       | document| extracted_text        | text  |

Rules:

- Using a field implicitly scopes the `types` facet (so `message.author` filters
  to `type=message`).
- **Field names are whitelisted via the registry; values are ALWAYS bound
  parameters.** No field name or value ever reaches SQL as a string. A query
  parser over operator input that compiles to SQL is a security path.
- Unknown field → a clean 422 (problem+json), never a silent empty result.

### 9.4 Testing bar (non-negotiable for a parser)

- Grammar unit tests + a fuzz pass that asserts no input produces raw SQL / no
  injection escapes the binder.
- **Backend parity**: a battery asserting the SAME query returns the SAME result
  set on SQLite and Postgres (the whole reason we own the grammar).
- Operator-typo resilience: malformed boolean / dangling operator degrades to a
  best-effort text search, not a 500.
