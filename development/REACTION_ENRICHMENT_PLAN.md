# Reaction enrichment plan

Status: DESIGN ONLY, not built. Captures the "who reacted" graph enrichment
(`message -> reacted_by -> actor`, `actor -> co_reactors -> actor`) and the
event-driven data pipeline it needs. Nothing here is committed to code yet.

The vision: expand a message on the graph canvas and see the actors who reacted
to it, carrying the emoji. "Saxworax and returnero both laughed at this" becomes
a first-class edge. On an actor, "who hypes this persona" becomes an affinity
hop. Reactions are a cheap, dense social-graph signal (agreement, allegiance,
mockery) that threat actors emit constantly and never think to hide.

---

## 1. Why this is blocked today

The enrichment plugin is ~15 lines and the registry auto-discovers it. The
problem is the data well is empty:

- `reaction` table: **0 rows, all sources.** The who-reacted evidence does not exist.
- The nine MortemTeam reactions we can see today are **aggregate counts** living
  in `message.source_specific.reactions` (the raw Discord `message.reactions`
  shape: `[{emoji:{name,id}, count}, ...]`). Emoji + count, never WHO.

So the enrichment would render as a button that expands into nothing. The data
pipeline has to land first, the plugin second.

### What already exists and works

- **Live capture half-exists.** `DiscordCollector._handle_reaction` already inserts
  a `ReactionTable` row on a live `MESSAGE_REACTION_ADD` gateway dispatch
  (idempotent on `evidence_ref`, drops if the target message is not yet stored).
  It is wired in `_dispatch` for ADD only.
- **Both graph endpoints are already indexed.** `actor` (50,264 rows) and
  `message` (911,844 rows) are in `search_document` via the event-driven
  `search_indexer` (`entity.actor.changed`, `raw.message.>`). So the enrichment
  needs **no new indexing**: the reaction row is a pure EDGE between two nodes
  that already hydrate. "Automagically indexed" is already true for the nodes;
  only the edge rows are missing.
- **The model is platform-agnostic and evidence-grade.** `ReactionTable` keeps
  one row per reaction event (not a mutated counter), with `redacted_at` for
  removals/redactions. Matrix `m.reaction` fits the same table. The enrichment
  reads the table, so it is cross-platform for free.

---

## 2. Architecture: three layers

### Layer A - live event path (event-driven, needs hardening)

This is the half that already runs. Every reaction that happens WHILE we watch a
monitored channel arrives as a gateway dispatch and lands in `reaction`
automatically. No tick, no poll. This is the "automagic" path the operator wants,
and for channels we join going forward it is the primary source of truth.

Gaps to close before it is trustworthy:

1. **REMOVE is not handled.** `_dispatch` wires `MESSAGE_REACTION_ADD` only.
   `_reaction_from_event` already parses the REMOVE shape, so wiring
   `MESSAGE_REACTION_REMOVE -> set redacted_at` on the matching row is small.
   Also `MESSAGE_REACTION_REMOVE_ALL` / `_REMOVE_EMOJI` (bulk clears) for
   completeness. Evidence posture: redact, never delete.
2. **Reactions to unstored messages are dropped.** `_handle_reaction` resolves
   the target by snowflake and drops on miss. Fine for a channel we monitor from
   join (we store messages live), but a reaction on a pre-join message never
   arrives as an event at all - that is Layer B's job, not a bug here. Document
   the boundary so nobody "fixes" it by storing orphan reactions.
3. **Depends on the monitored-channel gate.** Reactions only stream for channels
   in `_monitored`. Same gate as messages, so no extra work, but note it: an
   unmonitored channel yields no reactions even if we can see it.

### Layer B - historical backfill (one-shot replay, allowed by the event rule)

Live events only ever cover NOW forward. Every reaction that already happened
before we joined is invisible to the gateway and can only be pulled over REST.
Per the project rule, a one-shot is permitted precisely for "historical backfill
that replays onto the bus", which is exactly this.

The endpoint:

```
GET /channels/{channel_id}/messages/{message_id}/reactions/{emoji}?limit=100&after=<user_id>
```

- Returns the **user list** for one emoji on one message, paginated by `after`
  (ascending user id). Walk until a short page.
- Emoji encoding: a unicode emoji is the URL-encoded character; a custom emoji is
  `name:id`. `_emoji_str` already produces the canonical `name:id` form, so the
  encoder is shared with the live path.
- One call PER EMOJI PER MESSAGE. This is the cost center (see risks).

**Self-targeting worklist (the elegant part).** We do not need a separate queue.
`message.source_specific.reactions` already tells us, for every stored message,
which emoji carry a non-zero count. The backfill target set is:

> every stored message where, for some emoji, the aggregate count in
> `source_specific` exceeds the number of `reaction` rows we hold for that
> `(message_id, emoji)`.

That makes the pass **idempotent and resumable** with no extra state: as rows
fill in, the message drops out of the worklist on its own. It also reconciles
live + backfill automatically (a message that got all its reactors from live
events is already satisfied and never fetched).

**Cadence.** Rides `tick()` and the identity's `[delay_min, delay_max]` jitter,
bounded per tick like `_BACKFILL_PAGES_PER_TICK`, honoring the CF/429 pause. It
is a sibling of the message history backfill, not a new subsystem. A per-channel
or per-message cursor mirrors the existing `self._cursors` pattern.

### Layer C - the enrichment plugin (trivial, data-gated)

Once `reaction` has rows, the plugin is a drop-in `LocalSQLEnrichment` in
`eyenet/enrichments/builtins/` (the registry discovers it by `(src_type, name)`,
no dispatch to edit):

- **`MessageReactedBy`**: `src_type="message"`, `output_type="actor"`,
  `edge_kind="reacted_with"`. `build_select` = actor_ids from `reaction` where
  `message_id = src AND redacted_at IS NULL`. Neighbours hydrate from
  `search_document` (actors already indexed). ~15 lines, mirrors `MessageAuthor`.
- **`ActorCoReactors`** (optional, the juicy one): `src_type="actor" ->
  output_type="actor"`. "Actors who reacted to THIS actor's messages", a two-join
  (actor -> their messages -> reactions -> reactor actors), ranked by frequency.
  This is the allegiance/affinity hop. Likely `tier_gated` (social-graph intel).

Both are platform-agnostic: they read `reaction`, so Matrix reactions light them
up too with zero plugin changes.

---

## 3. The dedup keystone

Live (Layer A) and backfill (Layer B) must converge without double-counting. The
lever is the shared `evidence_ref`:

```
discord:reaction:{message_id}:{user_id}:{emoji}
```

Both paths compute the SAME ref and `evidence_ref` is `UNIQUE`, so an INSERT from
whichever path arrives second is an idempotent no-op (the live path already
catches `IntegrityError` and rolls back). This is what lets the two run
concurrently and lets the backfill worklist self-satisfy. Keep the ref identical
in both paths or the whole reconciliation breaks.

---

## 4. What "indexed" means here (and does not)

The operator's instinct was "put them in the DB and index them". Precisely:

- **DB:** yes - Layer A (live) + Layer B (historical) fill `reaction`.
- **Index:** nothing new required for the enrichment. The enrichment hydrates
  actor + message nodes that the `search_indexer` already maintains. The reaction
  is an edge, not a searchable node.
- **Optional extra:** if we want reaction COUNTS visible on an actor's or
  message's search card (e.g. "most-reacted message"), that is a `haystack`
  field addition in `search_indexer`, driven by a new `entity.*.changed` emit
  when a reaction lands. Separate, deferrable, not on the enrichment's critical
  path. Only build it if the operator wants reaction signal in global search.

---

## 5. Risks and open decisions

- **REST volume.** One call per emoji per message is the real cost. A spicy
  channel (dozens of emoji, hundreds of messages) is a lot of calls on a
  user-token that exposes no `x-ratelimit-*` headers (timing-based pacing only).
  Mitigations: cap reactor pull to messages above a count threshold; cap users
  pulled per emoji (top-N reactors, not every lurker); hard per-tick budget;
  respect the human-hours windowing TODO. Decide: do we want EVERY reactor, or is
  top-N enough for linkage? Linkage probably wants all of them, but the first cut
  can be bounded.
- **Edge payload.** `ExpandResult` edges are a fixed `{src_id, dst_id, kind}`
  shape. Carrying the specific emoji per edge needs an edge `fields` extension, or
  we fold the emoji into `edge_kind` (e.g. `reacted:fire`), or we aggregate per
  actor and drop the emoji on the edge. Decide before building the plugin.
- **Redaction race.** A reactor who reacted then un-reacted before our backfill
  runs is simply absent from the REST list - correct, no special handling. A live
  REMOVE after a backfill INSERT needs Layer A gap #1 (set `redacted_at`).
- **Bot reactions.** Discord drop-bots and role-react bots inflate counts. Decide
  whether to keep bot reactors (they are evidence of server automation) or filter
  `is_bot` actors out of the affinity hop (they pollute the social graph). Keep
  the rows, filter at the enrichment.
- **Custom emoji identity.** `name:id` is stable across a guild; the same visual
  emoji in two guilds is two ids. Fine - the enrichment keys on actors, not emoji
  identity. Only matters if we ever make emoji a node.

---

## 6. Build order

1. Layer A hardening: wire `MESSAGE_REACTION_REMOVE` (+ bulk removes) to
   `redacted_at`. Small, makes live capture trustworthy.
2. Layer B: the reaction backfill pass on `tick()`, worklist self-targeted off
   `source_specific` aggregate vs held rows, shared `evidence_ref`, bounded +
   jittered. This is where the real who-reacted corpus comes from.
3. Layer C: `MessageReactedBy` (then `ActorCoReactors`) plugins. Trivial once B
   produces rows.
4. Optional: reaction-count `haystack` field + `entity.*.changed` emit if the
   operator wants reaction signal in global search.

Layer C is the exciting 15 lines; Layers A+B are the unglamorous work that makes
it real. Do not ship C against an empty table.

---

## 7. Related

- `eyenet/enrichments/base.py`, `registry.py` - the plugin contract (auto-discovery).
- `eyenet/collectors/discord/real.py` - `_handle_reaction`, `_reaction_from_event`,
  `_dispatch`, `tick`, `_cursors` - where Layers A+B live.
- `eyenet/models/reaction.py` - the evidence table (platform-agnostic).
- `eyenet/search_indexer/` - event-driven node indexing (already covers actor+message).
- `development/poc-discord/DESIGN.md` - gateway + REST tradecraft, read-upward law.
- Memory: `project_discord_collector_reads_upward`,
  `project_enrichment_system_plugin_plan`, `feedback_event_driven_over_one_shot`.
