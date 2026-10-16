# Graph Explorer — interactive investigation canvas (sketch)

Status: **design sketch**. UX-first: this doc → interactive mockup → backend.
Supersedes the current `/graph` route (an actor-only search list, nothing more).

---

## 1. What it is

A Maltego-style **exploration canvas**, distinct from `/search`'s graph view.

- `/search/graph` = a FIXED induced subgraph of one query's hits. Stateless.
- `/graph` (this) = a STATEFUL graph the operator grows by hand. You drop ONE
  seed, its level-1 neighbors materialize, and you expand node by node, delving
  deeper. The canvas accumulates; nothing disappears unless you collapse it.

The unit of interaction is the **enrichment** (Maltego calls it a transform):
"given this node, show me its neighbors of kind X." Every node carries a menu of
the enrichments valid for its type. This is the whole mental model.

## 1a. Maltego-derived chrome (homage, not clone)

We pull the dock layout that makes Maltego legible, mapped to EYENET's corpus:

- **Entity palette** (left): the entity-type reference, categorized
  (Identity / Content / Infrastructure / Investigation), plus the seed search.
  Maltego drags *blank* entities to invent intel; our entities come from the
  corpus, so a palette type click just scopes the seed search to that type.
  (Operator-invented entities — a real name, an external BTC address — are a
  later add, asserted-only.)
- **Layout / view rail** (vertical, between palette and canvas): layout algos
  (organic / hierarchic / circular / grid), freeze/pin, fit, zoom.
- **Overview** (right, top): minimap with the viewport rect.
- **Detail** (right, mid): fields of the selected entity.
- **Run view** (right, bottom): a live log of enrichments as they run — matters
  because some enrichments are heavy reads (and future ones may be async).
- **Status bar**: `N entities · M links · zoom%`.
- **Iconographic nodes**: a per-type glyph on the colored disc, label below.

## 2. Node types (same palette as search graph)

actor · persona · crew · case · group · thread · message · artifact · source ·
**attachment** (colors tokenized: `--etype-*` in `lib/styles/colors.css`).

**Artifact kind is first-class.** `artifact` is the entity type; `kind` (open
varchar) is the sub-type and drives the node glyph + a signature tint:
onion / domain / fqdn / ipv4 / ipv6 / email / btc_wallet / xmr_wallet /
tron_wallet (and whatever extraction adds later). The palette lists kinds, not a
generic "artifact", and the detail header reads `[eyenet.btc_wallet]`.

**Provenance is a node property, not a type.** Every node is either *collected*
(from the corpus) or *operator-asserted* (hand-added by an investigator — a real
name, an external wallet, an off-platform actor). Operator nodes render with a
dashed gold ring, carry `added_by`, and have no enrichments; they link to the
graph only through operator-asserted edges (solid purple), never derived ones.

## 3. Enrichment catalog (the heart)

Each enrichment is one hop along a REAL relation (not the identity `graph_edge`
table, which is LINKED_TO/BELONGS_TO only). Source of truth in parentheses.

**actor**
- → messages authored            (message.actor_id)
- → threads started              (thread_op_authors)
- → groups active in             (message.group_id distinct)
- → artifacts used               (mentions of this actor's messages)
- → linked actors                (linkage)
- → related actors               (actor_relation)
- → persona                      (persona membership)
- → same-handle actors           (exact handle, cross-source — a HINT)

**artifact**
- → messages mentioning          (infrastructure_artifact_mention)
- → actors mentioning            (mention → message → author, deduped)
- → co-occurring artifacts       (artifacts sharing a message)
- → resolved source              (resolved_to_source_id, if RESOLVED)

**message**
- → author                       (message.actor_id)
- → thread / group               (message.group_id)
- → artifacts mentioned          (mention)
- → reply-to / forward-of        (message self-refs)

**thread**  → OP author · messages · group · participant actors
**group**   → source · threads · active actors
**persona** → member actors
**source**  → groups · resolved artifacts
**case**    → actors in case
**crew**    → member actors

**message** also → attachments           (attachment.message_id)
**attachment** (raw file, collector-side; `attachment` table)
- → source message                 (attachment.message_id)
- → uploaded by actor              (message.actor_id)
- → in thread / group             (via message)
- → document                      (document.sha256 == attachment.sha256 — same bytes)
**document** (analysed file, M10 pipeline; `document` table)
- → extracted artifacts           (infra extracted from extracted_text / embedded_meta)
- → source attachment / message   (sha256 bridge)
- → classification / PII          (document.classification)
- → uploaded by operator          (document.uploaded_by_user_id, when operator-added)

**No migration needed** — both tables exist (`eyenet/models/message.py`
`AttachmentTable`, `eyenet/models/document.py` `DocumentTable`) with storage
mixins. They have never been surfaced in the UI; this is where we start.
`attachment` and `document` are two node types joined on `sha256`: the
attachment carries provenance (who/where), the document carries the payload
(text, PII, artifacts found inside). AttachmentKind = image/video/audio/
document/sticker/voice/other.

## 4. The explosion problem (THE hard part)

One actor can author 500k messages; one group can hold 100k. We never dump that
onto a canvas. Strategy, in order of laziness:

1. **Every enrichment is capped** (default 25) and returns the TRUE total. The
   node shows `25 of 1,240`. "Expand more" paginates by cursor. (Maltego's
   core behavior. Ships first.)
2. **Degree preview**: before expanding, a node's enrichment menu shows each
   enrichment's count, so the operator sees `messages (1,240)` and chooses.
3. **Bundle nodes** for the worst offenders: `actor → messages` can collapse
   into per-thread or per-group bundle nodes ("84 messages in #leaks") that
   themselves expand. Deferred — only if cap+paginate proves painful.

`ponytail:` start at rung 1+2. Bundles (3) are real work; add them when a dense
graph actually hurts, not before.

## 5. Frontend state model

```
graph = { nodes: Map<key, Node>, edges: Map<key, Edge> }   // key = type:id
Node  = { type, id, title, fields, pos, pinned,
          expanded: Set<enrichment>,        // which enrichments already run
          counts:  Map<enrichment, total> } // for the degree preview
```

- **Dedup on `type:id`.** Expanding actor A and later message M that A authored
  must converge on the same A node, with the edge drawn once.
- **Seed**: search box (reuse `search_global`) → pick a hit → it becomes the
  only node → auto-run no enrichment (or a cheap default); operator expands.
- **Expand**: double-click = run default enrichment; right-click = enrichment menu
  (counts shown) + the existing operator actions (assert/retract edge, add to
  case, merge personas — all already in `search/+page.svelte`'s edge menu).
- **Collapse**: remove nodes a enrichment added that have no other anchor edge.
- **Layout**: incremental (fcose/cola) so existing nodes don't jump when new
  ones arrive. Pin a node to freeze it.
- **Persistence**: ephemeral first (localStorage snapshot of the canvas).
  Saved named investigations = later.

## 6. Backend primitive (derived AFTER the mockup locks UX)

One generic endpoint, per-enrichment, paginated:

```
GET /v1/graph/expand
      ?type={node-type}&id={uuid}
      &enrichment={name}&limit=25&cursor=...
  -> { nodes:[GraphNode], edges:[GraphEdge], enrichment, total, next_cursor }
```

Plus a cheap counts call for the degree preview (one row per enrichment):

```
GET /v1/graph/expand/counts?type=&id=  -> { messages:1240, artifacts:7, ... }
```

Storage: a `graph_expand(type, id, enrichment, limit, offset)` dispatch over the
existing relation primitives. Scope `read:search`. No new tables — this is all
reads over message / mention / linkage / membership.

## 6a. API audit (what exists vs. what we build)

Surveyed `eyenet/api/v1/` + storage mixins. Status per interaction:

**EXISTS — reuse as-is**
| Interaction | Endpoint | Note |
|---|---|---|
| Seed search | `GET /v1/search` (`search_global`) | cross-entity, cursor-paged |
| Assert operator edge | `POST /v1/graph/edges` | `asserted_edge.kind` is open varchar — predefined + custom labels both just store a string, no migration |
| Retract edge | `DELETE /v1/graph/edges/{edge_id}` | |
| Add node(s) to case | `POST /v1/cases/{id}/members` | |
| Artifact mentions | `GET /v1/artifacts/{id}/mentions` | the artifact→message provenance |
| Create crew / case / source | `crews_create` · `POST /v1/cases` · `sources_create` | operator-createable already |
| Upload document | `POST /v1/documents` (`documents_upload`) | operator file upload exists |

**PARTIAL — exists but needs extension**
| Interaction | Have | Gap |
|---|---|---|
| Node detail hydrate | `actors_get` · `sources_get` · `crews_get` · `*_manifest` (doc/attachment) | **no single-GET for group / thread / message / artifact** — Details can hydrate from the search-doc fields until added |
| Attachments of a message/thread/group | `list_attachments(mime, limit)` | **filters by mime only, not `message_id`** — add message_id filter (+ thread/group via message join) |
| Asserted edges for a node-set | `list_asserted_edges_for` (used by `search/graph`) | fold into `expand` responses |

**MISSING — net-new**
| Interaction | Needs | Notes |
|---|---|---|
| **Enrich (the whole tool)** | `GET /v1/graph/expand?type&id&enrichment&limit&cursor` | §6. Storage primitives exist (`message_authors`, `thread_op_authors`, `artifact_mention_edges`, `induced_edges`, `groups_messages`); no unified dispatch yet |
| **Degree preview** | `GET /v1/graph/expand/counts?type&id` | piecemeal counts exist (`count_artifact_mentions`, `count_graph_neighbors`, `count_documents/attachments`); need one roll-up per node |
| **Attachment → document (sha256 bridge)** | by-sha256 document fetch / join | `get_document` is by id only; add a `document_by_sha256` (both tables index `sha256`) |
| **Document → extracted artifacts** | a `document↔artifact` association | **real modeling gap**: artifacts link to messages (mention), NOT to documents. The "artifacts in file" enrichment has no backing edge — needs extraction wiring or a `document_artifact` table. Flag before promising it |
| **Operator entity creation** (actor/group/artifact/thread) | create endpoints + a **provenance flag** | only crew/case/source/document are operator-createable today. Actor/group/artifact/message have collector-only upserts. Decide: provenance column on the existing tables (`collected` vs `operator_asserted`) vs a separate operator-entity store. This gates both shift-drag and search→+add |
| **Saved graphs** (the picker) | `investigation_graph` + node-placement store + CRUD | no table, no endpoints. Holds name/owner/timestamps + per-node (entity_type, entity_id, x, y, pinned) + which enrichments were run. New migration |
| **Operator notes per entity** | notes field/endpoint on any entity | none today (cases have observations; entities don't). Mockup uses localStorage; real one needs a store. New migration |

`ponytail:` the explorer ships on `expand` + `expand/counts` alone (reads over
existing primitives, no migration). Saved-graphs, operator-entity creation,
document↔artifact, and per-entity notes are each their own slice with a schema
change — sequence them, don't block the read-only explorer on them.

## 7. Reuse map

| Need            | Reuse                                             |
|-----------------|---------------------------------------------------|
| Render surface  | `GraphCanvas.svelte` (Cytoscape, ctx menus)       |
| Seed search     | `search_global` / `/v1/search`                    |
| Operator edges  | assert/retract already in search edge menu        |
| Edge styling    | dashed=derived, solid=asserted (done)             |
| Colors          | `--etype-*` tokens                                |

New: the `/graph/expand` endpoint + per-type enrichment dispatch; the FE
stateful-canvas store (accumulate/dedup/expand/collapse).

## 8. Open forks (decide from the mockup)

- **A. Gestures — RESOLVED.** left-click = Details modal (150ms debounce) ·
  double-click = default enrichment · right-click = enrichment menu ·
  shift-drag = draw a link (rubber-band → edge-type picker on release) ·
  ctrl-drag = box-select. Operator entities: shift-drag a palette type onto the
  canvas, or search → "+ add new".
- **B. Explosion — RESOLVED (phase 1).** cap+paginate + degree preview. Bundle
  nodes deferred until a dense graph actually hurts.
- **C. Persistence — RESOLVED.** saved named graphs (picker landing page);
  needs the `investigation_graph` store (§6a MISSING).
- **D. Seed — RESOLVED.** both: a saved graph may auto-expand level-1 on open;
  a fresh seed drops bare and the operator chooses the first enrichment.

## 9. Edge-type picker (next build step)

On shift-drag release, the picker offers predefined operator relations
(`same as`, `associate of`, `controls`, `member of`, `uses`,
`communicates with`, `related to`) plus a **custom** free-text type. Backed by
`POST /v1/graph/edges` — `asserted_edge.kind` is open varchar, so predefined and
custom are the same write, no enum, no migration.
