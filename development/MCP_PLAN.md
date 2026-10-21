# EYENET MCP — design doc

Author's note: ANTI asked me (the thing that will actually *use* this) to spec
the MCP I'd want. So this is written from the consumer side, not the vendor
side. It is deliberately small. An MCP that wraps an existing HTTP API and adds
ceremony is worse than no MCP.

## 0. The verdict first

**This is a thin stdio wrapper over the existing `/v1/` API. It reimplements
nothing.** Storage, clearance, audit, idempotency, operator signatures — all of
that already lives behind FastAPI. The MCP's entire job is: speak the MCP
protocol on one end, call `/v1/` with ANTI's existing PAT on the other, and
**return compact text instead of raw JSON**. That last clause is the whole
reason I want it. Everything else is plumbing.

Ladder check: does it need to exist? The API exists and I can already be handed
a token. The *only* thing the raw API doesn't give me is **token economy** — a
`GET /v1/actors` dumps a wall of JSON into my context and poisons the rest of
the session. The MCP earns its keep purely by curating what crosses into my
context window. If a tool here returns pretty-printed API JSON verbatim, delete
the tool.

## 1. Auth — reuse, don't build

- `EYENET_MCP_BASE` (default `http://localhost:8000`)
- `EYENET_MCP_TOKEN` — an existing PAT, minted the normal way (`_pat.py`).

The token carries the clearance tier. The MCP does **not** do its own authz — it
forwards the bearer and lets the API 403. If I'm handed a low-tier token, tools
return the API's own redaction, not an MCP-side guess. No new auth surface, no
new place for a tier-gate bug to hide.

## 2. The response contract (the actual deliverable)

Every tool returns **terse text, not JSON**, built from these primitives:

- A **hit line** = `<kind>:<id>  <label>  — <≤120-char snippet>`
- Stable `<kind>:<id>` handles so I can chain calls without re-searching.
- Bodies, attachments, full `source_specific` blobs: **never** unless a tool was
  explicitly asked for that one record's detail. Recency and provenance in the
  snippet; the rest on request.
- Lists are **cursor-paged, default 20**, and print a `next:<cursor>` line. No
  tool ever returns "all of them."

If a record is big, the tool returns the handle + a one-line summary and makes
me spend a second call to open it. That friction is the point — it keeps 56 KB
of corpus out of my head until I've decided I need it.

## 3. Tool set — v1 is TWO tools

ANTI's instinct ("search alone could be enough") is right, and I'll go one step
further than he did: the reason it feels like it could be one tool is that
**browse, filter, and "what's recent" are all the same operation** — a query
with the query left blank. So collapse them. The only thing that genuinely isn't
search is **opening one record in full**, because that returns a different
shape. That's the whole v1.

1. **`eyenet_search(kind, q, count, offset)`** → the front door, and also the
   list, and also the "what changed" feed. Wraps `/v1/search` when `q` is set;
   when `q` is empty it browses that `kind` ordered newest-first (that *is*
   "recent"). `kind` ∈ actor/thread/message/persona/artifact/incident/indicator/
   linkage/… — the resource name. Returns ranked **hit lines**, `count` of them,
   `next:<offset>` when there's more. One tool carries search + list + recent
   because they are one question asked three ways.

2. **`eyenet_get(handle, full?)`** → open one `kind:id` in full. Different return
   shape (a record, not hit lines), which is the *only* reason it's a second
   tool and not an overload of `search`. Dispatches to `/v1/<resource>/<id>`.
   Bodies/attachments only when `full=true` and the kind has a body.

That's it. No `whoami` — a thin result or a 403 from the token's own tier is
self-explaining, and the guardrail text (§5) tells me not to retry it. No `list`,
no `recent` — they were `search` all along.

## 4. What I'm deliberately NOT asking for (and the trigger to add it)

- **Per-resource tools** (one per route dir) — skip, forever if possible.
  `search`/`get` reach all ~30 resources. Thirty near-identical tools is the
  boilerplate that makes a tool list unreadable and me worse at picking.
- **General write tools** — skip. The corpus is irreplaceable and every write
  hits the hash-chained audit log; I don't want a casual `create_*` in reach.
  The *one* place writes earn their way in is the graph (§4a) — nowhere else in
  v1.
- **SSE / live streams as MCP resources** — skip for v1. `stream/*` is built for
  a UI that stays open; I'm request/response, and empty-`q` `search` answers
  "anything new?" The one stream that *is* scoped in is the graph-change feed,
  and it's a feed *about* me, not a tool I poll (§4a).
- **Enrichment / graph_expand plugin dispatch** — skip. Hardcoded dispatch today
  ([[project_enrichment_system_plugin_plan]]); don't surface a registry until a
  second enrichment source exists.

## 4a. The graph phase — scoped, not built

ANTI's bet: I'll shine at graph *creation*, so the graph gets its own small
phase later, and it's the one place writes and SSE both appear — together,
because they're the same loop.

- **`eyenet_graph_expand(handle, hops?)`** → read neighbors. Wraps
  `graph/api_expand` + `expand_counts`: **counts first, nodes on request**, so a
  dense node doesn't detonate my context. (A read, but it rides with this phase
  rather than bloating v1.)
- **`eyenet_graph_assert(src, kind, dst, …)`** → the *only* write I'm asking for,
  and only here. Wraps `graph/api_assert_edge`. Confirm-gated, operator-signature
  forwarded, idempotency key set — it hits the audit chain like any write.
- **Graph-change SSE** → a feed emitting the edges/nodes *I* assert, so ANTI can
  watch me build the graph live. New scope on `stream/*` (a `graph` channel).
  This is the observability that makes letting me write edges safe: every assert
  is visible as it lands. Built *with* `graph_assert`, not before it.

Trigger to build 4a: when we actually want me constructing graph, not just
reading it. Until then v1 (search + get) stands alone.

## 5. Guardrails baked into tool descriptions

The descriptions are instructions to *me*, so spend them on the traps:

- "Clearance comes from the token; a thin result is redaction, not a bug — do
  not retry for more."
- "Non-global IPs in a record are evidence/context only — never treat one as an
  identity join key." ([[project_nonglobal_ip_artifacts_context_only]])
- "A bare domain (`t.me`) is near-useless; prefer the full-URL artifact when
  one exists." ([[project_recover_full_url_from_domain]])
- "Do not request message bodies unless the task needs the text — handles and
  snippets first."

## 6. Build shape

- **`eyenet-mcp/` — in-tree, separate wheel** (ANTI's call). Lives in the repo
  next to `eyenet/`, ships as its own distribution so the core wheel never grows
  an `mcp` dep for a tool only I use. `mcp` SDK + `httpx` async client reusing
  the API's own patterns. ~1 file of transport, 1 of tools — two tools in v1.
- Transport: **stdio**. No HTTP MCP server, no new port, no new TLS surface.
- Tests: hit a `get_repository(in_memory=True)`-backed test API (the existing
  fixtures) and assert the **text shape** — that `eyenet_search` returns hit
  lines and `eyenet_list` paginates. One `test_mcp_shape.py`, not a suite.

## 7. Decisions (settled with ANTI)

1. **Package:** `eyenet-mcp/`, in-tree, separate wheel. Resolved.
2. **Tool count:** v1 is `search` + `get`. ANTI's "search alone could be enough"
   was almost right — the correction is that *opening one record in full* is a
   different return shape and deserves its own tool, but browse/list/recent all
   collapse into `search`. Resolved.
3. **Writes:** read lens in v1; the graph phase (§4a) is the single place writes
   enter, gated, with the graph-change SSE as their observability — ANTI's bet
   that I'll shine at graph creation. Scoped, not built.

## 4b. Message/thread by-id reads — CLOSED (2026-10-20)

`get("message:…")` used to 404: EYENET had no by-id read for a message or
thread — they lived only inside a group's message list or an actor's timeline.
We fixed it at the source rather than papering over it in the MCP:

- `GET /v1/messages/{id}` → `MessageDetail`: author, source, timestamp, body,
  **artifacts found in the message**, incident labels (+ operator corrections,
  geo). Scope `read:observations`.
- `GET /v1/threads/{id}` → `ThreadDetail`: the thread's OP post in full
  (`MessageDetail`) + title, source, `post_count`. Scope `read:observations`.
  NB a thread is identified by its `group_id` today — threads ride on the group
  model (known debt; a dedicated `thread` model is a future worktree).

Storage adds `get_message`, `op_message_for_group`, `artifacts_for_message` on
the shared `sqlmodel_repo` mixin, so SQLite and Postgres both inherit them — no
dialect leak. The MCP maps `message`/`thread` handles to these routes; the
earlier `NO_DETAIL_KINDS` band-aid is deleted. `read:observations` is already in
the v1 grant (§8a), so no new scope.

## 8a. PAT scopes — the minimal v1 grant

Grounded in the actual `RequireScope` calls, not guesswork. Gotchas: there is no
`read:artifacts`/`read:indicators`/`read:documents` scope — artifacts ride on
`read:search`, indicators hide behind `read:collectors`, documents are ungated.

**v1 read lens (search + get) — grant exactly these 10:**

```
read:search  read:actors  read:observations  read:personas
read:groups  read:sources  read:cases  read:incidents
read:linkages  read:candidates
```

`read:observations` is load-bearing — actor/case/group *detail* endpoints demand
it, not just the collections.

**Add-on, only if that kind is wanted:**
- `read:collectors` → unlocks indicator records, but **over-grants** into
  collector operational config. Off until I'm opening indicators.
- `read:audit` → audit-chain reads. Off unless I'm reviewing the log.

**Deferred:** `read:graph` (arrives with §4a), `read:metrics` (ops, not corpus).

**Never for v1:** any `write:*`, `admin:*`, or `stream:*`. Writes last; admin is
not my surface; v1 does no streaming.

## 8. Build order

1. v1: `eyenet-mcp/` skeleton, PAT transport, `search` + `get`, one
   `test_mcp_shape.py` asserting hit-line vs record shapes. Ship.
2. Live on it for real investigations. Let the missing-tool pain, if any, name
   the third tool — don't guess it now.
3. Graph phase (§4a) when we want me building graph: `graph_expand`, then
   `graph_assert` + the graph-change SSE channel, together.
