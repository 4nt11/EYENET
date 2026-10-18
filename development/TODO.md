# TODO

Deferred work, captured so it isn't lost. Not in priority order.

## Telegram attachment bytes — DONE 2026-10-18 (backfill HELD, pending trigger)

The TG collector shipped a metadata-only stub (fake sha256, 0-byte images, no
blob); ~50k live attachments are hollow shells. Fixed:
- Forward path downloads + stores bytes within an admin-tunable size gate
  (`telegram.attachment_max_bytes`, default 3 MiB; photos always pulled). Over the
  gate: metadata + `source_ref` t.me link only. Downloaded TG media = tier NORMAL.
- Settings KV + admin API (`GET/PUT /v1/settings/{key}`, scope `admin:settings`).
- Backfill of the 50k shells runs in-collector, driven by
  `telegram.attachment_backfill_per_tick` (default 0 = HELD). To run: PUT that
  setting to N (shells re-pulled per collector tick, throttling the live session);
  set back to 0 to pause. Resumable (shell = `source_ref IS NULL`).
- NOT YET DEPLOYED as of this note: the forward download is a live behavior change
  on covert sessions — redeploy eyenet:base to activate it.
- Follow-up: surface `source_ref` in the attachment manifest/list API + FE so an
  operator can click the link (graph node already carries it).

## Documents (M10) pipeline has ingested ZERO rows in prod (noted 2026-10-18)

`DocumentTable` is empty live; the only "documents" are `DOCUMENT`-kind attachments
in chats. The search clearance gate (migration 0015) is therefore preventive. If
doc ingest is wanted, wire `DOCUMENT`-kind attachment blobs -> the M10 pipeline.

## POST /v1/identities — session-file upload (provision an identity from the UI)

**Vision:** configure a new Telegram (or Matrix) identity by uploading its
`.session` file and metadata, instead of the current `identities.toml` +
`eyenet identity sync` CLI/config flow.

**Shape:** `POST /v1/identities` multipart — the `.session` blob + `{name,
source_id, role, cooldown_seconds?, proxy_uri?}`. Handler encrypts the blob at
rest (writes `session_path`), then `create_identity(...)`. Returns
`IdentityDetail` (the read schema from the identities-read PR).

**Why it's deferred / build with eyes open:** the `.session` file is effectively
a full account-takeover credential. The current design deliberately keeps it
OFF the network surface (operator handles the file locally; `session_path`/
`proxy_uri` are also omitted from the read API). An upload route is a real
attack-surface expansion. Requirements when we build it:
- `write:identity` + admin gate; audit every upload (who, when, which source).
- Encrypt at rest; never echo the blob back; `session_path` stays off reads.
- Validate the uploaded blob is a real session before persisting.
- Consider size limits + the interactive Telethon auth story (the operator
  still has to obtain a valid `.session` out-of-band first).

Pairs with the read surface (`GET /v1/identities` + `/{id}`) already shipped,
and fully unblocks a "provision identity from the UI" flow.

## Audit-anchor external sinks (§5.9) — dispatch to external witnesses

**Shipped:** the anchor subsystem records signed `(audit_head, journal_head)`
heartbeats (`AnchorEmitter` + `eyenet anchor`), stores them, publishes each on
`eyenet.audit.anchor`, and serves them via `GET /v1/audit/anchors`.

**Deferred:** the operator-configured *external sinks* that actually deliver
anchors to third parties — file drop, webhook POST, email. §5.9's whole point is
that an outside party holds a copy, so a rolled-back or forked chain is
detectable. The bus subject is the machine-readable feed a sink consumes; the
sink deliverer itself is a separate config + delivery subsystem.

**Shape when we build it:** a small dispatcher subscribing `eyenet.audit.anchor`
(or reading the table) with per-sink config (`[audit.anchor.sinks.*]` TOML:
kind=file|webhook|email, destination, retry/backoff). Delivery is best-effort +
durable-retry; a sink failure must never block the emitter. Consider a
delivery-receipt log so the operator can prove an anchor reached witness X.

## Clearance bootstrap — admin must self-grant `admin:clearance`

**Not a bug, a §4.8 design consequence worth surfacing:** `admin:clearance` is a
grant-only scope, in NO role baseline. So the clearance page (and the 4 grant
handlers) return **403** until an operator explicitly grants themselves the
scope via `eyenet user scopes`. First-run UX gap: a fresh admin sees "forbidden"
with no in-product hint.

**Options when we polish:** document the `eyenet user scopes ... admin:clearance`
bootstrap step in the operator guide; and/or have the FE render a clear "you need
an admin:clearance grant" affordance on 403 instead of a generic error.

## Classifier Docker image — finish the REQUIRES-TUNING scaffold

`deploy/docker/Dockerfile.classifier` builds but is not turnkey. nsjail needs
`CLONE_NEWUSER` + its own seccomp, so the compose `classifier` profile runs with
`security_opt: seccomp=unconfined` + `cap_add: SYS_ADMIN` (least-bad on a single
host). Before it classifies for real:
- **Vendor `nsjail`** — not in Debian repos. Drop a prebuilt static binary at
  `deploy/docker/nsjail` (the Dockerfile COPYs it) or add a build stage.
- **Pin the extract-venv deps** from the real extraction requirement set — the
  current list (`pymupdf`/`python-docx`/`presidio-analyzer`/`pytesseract`/`pillow`)
  is the expected shape, not a verified pin.
- Then tighten the container privileges back down once a real classify runs
  end-to-end. Kept an opt-in profile so the core stack ships without it.

## `eyenet deploy` installer CLI — build it

Spec'd in `deploy/DEPLOY.md §5`, not implemented. One-shot root bootstrap
mirroring `decnet init` (`../../DECNET/decnet/cli/init.py`): Jinja2-render the
`deploy/*.j2` set + `eyenet.target` into `/etc/systemd/system`, install
polkit/tmpfiles/logrotate, seed user/group/dirs, `systemctl enable --now
eyenet.target`. Flags: `--dry-run/--no-start/--force/--deinit/--purge/
--user/--group/--install-dir/--venv-dir/--data-dir/--prefix`. Name it
`eyenet deploy` (NOT `eyenet init` — that's DB init; don't overload it).

## Matrix collector E2EE (libolm) — decision pending

`libolm3` is now in the Docker runtime image so `matrix-nio[e2e]` imports, but
E2EE stays OFF by design (M7 shipped no-E2EE; see `project_m7_done`). If/when we
want Megolm decryption + a persistent device store, wire it deliberately (and
add `libolm-dev` to the builder stage if python-olm ever needs to compile).

## `MissingGreenlet` teardown noise in the bus workers

Benign but noisy: SQLAlchemy+aiosqlite logs "Exception during reset" /
`MissingGreenlet` when a pooled connection is finalized outside the event-loop
greenlet on worker shutdown. Harmless (operations already committed) but pollutes
logs. Fix by disposing the async engine / sessions cleanly on `ServiceBase`
shutdown before the loop closes.

## Collector control-plane vs data-plane are decoupled — MOSTLY FIXED

`CollectorSupervisor.reconcile_collectors()` now actually **spawns** the collector
child (`python -m eyenet.cli collector --identity ... --type ...`) when
`desired_state=running`, tracks the process handle, terminates it on stop, and
drives `observed_state` from real process liveness (RUNNING while alive, CRASHED
+ COOLING backoff `min(2^restart_count, 600)s` on unexpected exit). Clicking
"start" in the UI now launches a real collector.

**Remaining loose end:** the spawned child still claims its **identity by name**
via the DB pool, not by `collector_id`. observed_state is now process-liveness
(handle presence), but it is NOT yet a data-plane heartbeat: a spawned process
that connects but silently stops ingesting still shows RUNNING. Bind the child to
its `collector_id` (pass `--collector-id` / register against the row) and add a
real ingest heartbeat so the row reflects actual collection, not just liveness.
The compose `collector` service (pinned `--identity=scout01`) is now redundant
with supervisor-spawning and will double-claim — remove it from the compose stack;
the supervisor is the launcher.

## M9 HTTP API — unfinished endpoints (was the pre-incident-detection backlog)

Captured from the old NEXT_SESSION handoff (2026-09-22) before it was rewritten for
the incident-detection work. This is real, live, unfinished API surface.

### 5 live `501 NotImplementedError` stub handlers
Grep to confirm current state: `grep -rn "raise NotImplementedError" eyenet/api/`.
Schemas already exist (`ClearanceGrantSummary`, `CursorPageClearanceGrantSummary` in
`api/v1/schemas/clearance.py`); opIds pinned → no OpenAPI change, just fill the body.

| Endpoint | Handler | Storage status |
|---|---|---|
| `GET /v1/clearance/grants` (list) | `clearance/api_list_grants.py` | needs `list_clearance_grants`+`count_` (filters: user_id, scope, active_only) |
| `GET /v1/clearance/grants/{id}` | `clearance/api_get_grant.py` | needs `get_clearance_grant(grant_id)` |
| `POST /v1/clearance/grants` (grant) | `clearance/api_grant_clearance.py` | `storage.grant_clearance(...)` EXISTS — wire handler + audit |
| `POST /v1/clearance/grants/{id}/revoke` | `clearance/api_revoke_grant.py` | `storage.revoke_clearance(...)` EXISTS — wire handler + audit |
| `GET /v1/audit/anchors` | `audit/api_list_anchors.py` | **likely DONE** now (see the audit-anchor TODO above says it serves) — VERIFY, drop if shipped |

Gotchas: clearance handlers use raw `Query()` (not shared `cursor_params`);
`include_total`/`active_only` are **int 0/1, not bool**. Storage reads = per-domain
mixin `list_/count_` + ABC twins in `repository.py`, ANSI-only. New test dir needs
`__init__.py`. (Also: `admin:clearance` is grant-only → page 403s until self-granted,
see the "Clearance bootstrap" TODO above.)

### Auth surface — only 4 of 14 endpoints wired (login/verify/logout/me)
Not wired (verify each isn't also a 501 before building FE):
- **PAT tokens** `GET/POST/DELETE /v1/auth/tokens` — simple CRUD + account/settings UI.
- **MFA self-enroll** `POST /v1/auth/mfa/enroll` + `verify-enroll` + `DELETE` — secret/QR + verify.
- **token refresh** `POST /v1/auth/refresh` — client auto-refresh on 401, no page.
- **stream-token** `POST /v1/auth/stream-token` — mints the SSE JWT (blocks SSE below).
- **signing-key** `POST /v1/auth/signing-key/challenge` + `/signing-key` — the **M9.B2
  keystone** (client-side Ed25519). NOT simple. Unlocks reclassify signed bodies, signed
  document/attachment byte access, and the file-access journal reader.

### SSE live streams — 0 of 5 wired
`/v1/stream/{linkages,personas,audit,control,all}`. No EventSource in FE (unbuilt
`stream` nav slug). Needs stream-token first.

### Backend gated on M9.B2 signing
`/v1/audit/file-access` + `/by-user` journal reader; reclassify signed flows; signed
byte access — all DISABLED affordances in the UI today until signing lands.

**Recommended order when resuming API work:** finish clearance (4 handlers; 2 have
storage) → PAT tokens → M9.B2 signing (unlocks the rest incl. SSE via stream-token).

## Incidents free-text search — `GET /v1/incidents?q=`

**Vision:** search the incident triage feed by message content, alongside the
label filter + offset paging already shipped (`recent_incidents(limit, label,
offset)`). An analyst types "bulk sms" or a @handle and gets matching incidents.

**Shape:** add a `q` query param to `list_incidents`. The incident table holds
only `message_id` (no body), so search means an **incident → message join** with
`LIKE '%q%'` on `message.body` (and optionally `group.current_title` /
`actor.current_handle`, since the feed now surfaces those — see the actor-
correlation feature, `message_context_by_ids`). Push it into `recent_incidents`
(a new `q` arg) so it composes with `label`/`offset` in one query, newest-first.

**Why deferred / build with eyes open:**
- **Scale:** a bare `LIKE '%q%'` scans every message body (155k+ rows) per query —
  fine at small-operator scale, ugly as the corpus grows. The real fix is an
  **FTS5 virtual table** over message bodies (SQLite full-text; dialect-specific →
  belongs in the SQLite backend override per CLAUDE.md §2.3 Rule 1, with a generic
  `LIKE` fallback in the mixin). Ship `LIKE` first, add FTS5 when it bites.
- **Injection:** `q` is a bound param (SQLAlchemy `.like(f'%{q}%')` parameterizes
  the whole pattern) — safe — but `%`/`_` in `q` act as wildcards; escape them if
  literal matching matters.
- FE: a search box on the incidents page (`incident.svelte.js` `loadIncidents(label,
  q)` → `?q=`), debounced. The list rail already shows channel + body preview.

**Done already (context):** label filter is in-query, offset paging works, and each
incident carries group + actor (who/where). Search is the last of the three
"genuinely amazing" asks (search / filtering / actor correlation).

## QR login — QR code does not regenerate in the UI on expiry

The server driver (`eyenet/api/auth/_qr_login.py` `_run_login`) DOES call
`qr.recreate()` on `qr.wait` timeout and updates `state.qr_url`, and the poll
returns the fresh `qr_url` — but in practice the displayed QR does not refresh
before Telegram's ~30s token expiry, so a slow scan fails against a stale code.
Observed live 2026-09-23; provisioning itself works (scan promptly and it's fine).

**Shape when we fix it:** verify the recreate loop actually advances `state.qr_url`
(is `_QR_REFRESH_SECONDS=25` firing? does telethon's `recreate()` mutate in place
vs return a new object the driver must reassign?), and that the FE `$effect` in
`src/routes/identities/provision/qr/+page.svelte` re-renders on `qrCtx.qrUrl`
change (poll cadence is 2s, so a changed url should re-render within 2s). Likely a
driver-side reassignment bug or the poll not observing the new url. Add a visible
"code refreshed" tick + a manual "regenerate" button as a fallback.

## Circadian timezone inference + operator presentation

**Status:** the four `circadian.*` primitives (BEHAVE-TEXT 0.1.4) are LANDED and
backfilling — `hour_histogram[24]`, `dow_histogram[7]`, `hour_dow_histogram[168]`,
`quiet_span_utc[2]`, all UTC, in `temporal_summary`. This TODO is the CONSUMER
side: turn those raw UTC distributions into an operator-facing "Place/Timezone"
(e.g. `America/Santiago`) panel. Deliberately deferred so the overnight backfill
produces the data the recipe reads.

**Dumb-extractor / smart-consumer boundary (already decided):** BEHAVE never emits
an inferred tz. The inference lives EYENET-side as an engine recipe + a derived
profile field. The primitives stay UTC.

**Inference recipe (new, over `temporal_summary`):**
- Offset: cross-correlate `hour_histogram` against the 24 candidate UTC offsets,
  OR map the `quiet_span_utc` midpoint to a local sleep-center (~03:00-04:00 local)
  → best UTC offset. Produces e.g. `UTC-03:00`.
- **Offset → IANA name is many-to-one** (`-03:00` = Santiago / São Paulo / Buenos
  Aires …) and DST-ambiguous. Timing ALONE must only yield an offset + a candidate
  zone LIST, never a single zone asserted as fact.
- **Disambiguate by fusing signals** — this is the money path and what makes a
  single IANA name defensible:
  - `dialect_region` (es-CL Chilean Spanish → America/Santiago)
  - victim-country / geo signals on the actor
  - observed languages
  Offset + dialect agreeing on one zone ⇒ high confidence.
- DST: pick standard vs daylight using the actor's active date range.

**Derived profile field:** `temporal_summary.inferred_tz = {offset, zone_best,
zone_candidates, confidence, supporting_signals, local_active_window,
local_quiet_window}`. `zone_best` is null when only timing is available (show the
candidate list instead).

**Operator panel (actor detail → "Activity rhythm"):**
```
Local timezone   America/Santiago  (UTC-3)   ◆ high · circadian + es-CL
Active window    09:00 - 01:00  (local)
Sleep gap        04:00 - 11:00 UTC  ->  01:00 - 08:00 local
Hours (UTC)   ▁▁▁▂▅▇▇▆▅▃▂▁▁▁▁▂▃▅▆▇▇▅▃▂     (24-bin sparkline)
Week          M▇ T▇ W▇ T▆ F▇ S▃ S▂          (weekday vs weekend)
```
Degraded (timing only, no dialect): `UTC-03 · candidates: Santiago / São Paulo /
Buenos Aires · medium`. NEVER a false single zone.

**Honesty rules (load-bearing — this is forensic evidence):**
- Confidence must reflect `meta.total_messages` (a 3-msg histogram is noise).
- When `hour_histogram` is poisoned by day-granular timestamps (bin 0 spike), fall
  back to `dow_histogram` and down-rank the offset confidence.
- The tz is always a HINT with its supporting signals shown, never bare fact —
  breaks for shift workers, teams, scheduled bots, and cross-tz merged personas.

**Verifier:** circadian overlap (histogram cosine / EMD) is a cheap,
language-agnostic linkage feature — unlike the Spanish-disabled stylometric
simhashes. Worth adding to the linkage score once profiles carry the histograms.

---

## Artifact enrichment — derived/external context per artifact

**Vision:** the Artifacts browser (`/artifacts`, shipped 2026-10-15) shows a
value + its mentions (who/where/when). Enrichment adds DERIVED context so an
operator sees what an indicator *is*, not just that it appeared:
- IPs → geolocation, ASN/owner, reverse DNS, passive-DNS history.
- domains → WHOIS (registrar, creation/expiry), current resolving IPs, NS.
- wallets → chain, balance, tx count, first/last activity (block explorers).
- onions → liveness, page title/fingerprint.
- emails → provider, breach appearances.

**Architecture (direction; confirm scope before building):**
- EVENT-DRIVEN on the bus — NOT a one-shot CLI, and NOT in the per-message
  extraction hot path. An `EnrichmentService(ServiceBase)` subscribes to artifact-
  change events: extraction ALREADY publishes `entity.artifact.changed` (the
  SearchIndexer consumes it to reindex) — enrichment is a peer consumer of the
  same subject. A new/changed artifact triggers enrichment reactively, exactly as
  search reindexes reactively. Extraction stays dumb + fast; enrichment is a
  downstream service, multi-instance from day one ([[plural-services]]).
- Passive enrichment (offline GeoIP/ASN, cached passive-DNS, our own prior
  observations) fires automatically on the event. ACTIVE enrichment (see OPSEC
  below) is NOT auto-fired — it enqueues an operator-approval task, opt-in per
  artifact.
- Initial corpus catch-up is a REPLAY onto the same subject (an `enrich-backfill`
  that only PUBLISHES artifact events for the existing rows, never a parallel
  one-shot that does the enrichment inline) — the service stays the single code
  path, same way search bootstrapping feeds its indexer. One path, not two.
- Storage: a separate `artifact_enrichment` table (artifact_id FK, provider,
  fetched_at, data JSONB, ttl) — NOT columns on `infrastructure_artifact`. The
  artifact row is evidence; enrichment is derived, mutable, refreshable, may be
  absent, and is one-to-many per provider.
- Browser: render enrichment in the artifact detail panel (new API field/route).

**OPSEC — load-bearing, this is covert tradecraft:**
- An ACTIVE lookup (WHOIS, live DNS resolve, block-explorer query, onion fetch)
  TOUCHES or LOGS against the target's infrastructure and can tip off the actor
  or leak our interest to a third party. Distinguish it from PASSIVE enrichment
  (offline GeoIP/ASN DBs, cached passive-DNS, our own prior observations), which
  is safe.
- Passive enrichment may be automatic; ACTIVE enrichment is OPT-IN, operator-
  triggered per artifact, audited, and routed through our egress controls (Tor /
  the identity proxy where appropriate) — never a bulk auto-sweep that
  fingerprints the whole corpus to external services. Respect the curl/wget block;
  use the sanctioned HTTP path.
- Rate-limit + cache aggressively; external providers throttle and log.

**Why deferred:** needs provider choices, the egress/OPSEC model, and the storage
+ API + FE surface. Parked after the Artifacts browser. See memory
`project_artifact_browser_and_enrichment`.

## Artifact kind — two edge cases from the coded extractor build (2026-10-15)

The coded domain/IP extractors shipped; these are the remaining edges, NOT the
extraction work itself:
- **URL-host IPs still land as DOMAIN.** `_classify_and_normalize`
  (`url_extraction.py`) runs `normalize_host` on a URL host, and
  `idna.encode("1.2.3.4")` succeeds, so an IP inside `http://1.2.3.4/` is stored
  as DOMAIN (the URL pass adds it before `_find_ips`, and value_hash dedupes on
  value → DOMAIN wins). Fix: try `ipaddress.ip_address(host)` in
  `_classify_and_normalize` and return None so the coded IP path owns it.
- **Retag pre-existing DOMAIN rows that are actually IPs.** Old url_extraction
  stored URL-host IPs as DOMAIN; `artifact-backfill` WON'T fix them because
  value_hash dedupes on value alone (the existing DOMAIN row is found, kind
  unchanged). One-off UPDATE: DOMAIN artifacts whose `value` parses as a non-
  unspecified `ipaddress.ip_address` → retag ipv4/ipv6, then `search-backfill`
  (do it after the fix above so new writes are already correct).

## Incremental per-actor MFW stylometry profiles (2026-10-16)

**Full spec:** `development/STYLOMETRY_MFW_PLAN.md` (schema, phasing, open
decisions). This TODO is the pointer + the decisions already locked.

**Vision:** a per-actor distribution of Most Frequent Words, maintained
INCREMENTALLY on ingest (counts are additive, so ingest is `+=`, never a
recompute) and compared on demand in the Verifier. Cheap, interpretable,
language-agnostic authorship signal that complements LUAR (LUAR wins
cross-context; MFW wins same-register). Runs in <8GB. See
`[[project_luar_stylometry_poc]]`, CLAUDE.md §5 (locale-agnostic primitives).

**Locked decisions:**
- **Ship all THREE comparators** off the same stored counts, pick/ensemble by
  data regime: raw **MFW-cosine** (relative-freq cosine, best at higher token
  volume), classic **Burrows-Delta** (z-score + Manhattan, stronger on LITTLE
  data), and **Cosine-Delta** (z-score + cosine). All three are near-free once
  the counts exist, so there is no reason to pick one.
- **Data-driven vocab, NO hand-built word lists.** The top-N emerges from a
  per-locale global frequency table. Scales to every language for free.
- **CJK + Thai are IN SCOPE** (ANTI's call; the backfill locale histogram will
  prove the actors are there). Whitespace tokenization is therefore rejected.

**Resolved 2026-10-16:**
- Tokenizer: **ICU word-seg (primary) AND char-n-grams (reuse `_ngrams` from
  `character_ngram_simhash.py`)**. Both ship; M5 grid weights them. ICU dep
  approved (needs libicu in the Docker images, like libolm).
- Exactly-once: **reuse the existing `corpus_cursor`** per-`(actor,
  primitive_name)` watermark — the StylometricSensor already drives every window
  primitive off it. MFW is just another primitive. NOT a `message` nullable
  column (mutates evidence, MFW-specific sprawl), NOT a new table.
- This GENERALIZES `function_word_distribution_top50.py` (EN/ES hardcoded,
  Latin-only regex, lossy `simhash64`): keep the FULL per-locale data-driven
  distribution, drop `simhash64` (the step `poc-luar` showed killed precision),
  swap tokenizer for ICU, maintain incrementally. Reuse MIN_MESSAGES=30/
  MIN_TOKENS=500 as the floor precedent.

**Still open:** Delta N + comparator weights (seed from `poc-luar`, tune on M5);
v1 scope (counts + backfill + comparator first, viz + calibration after).

**Load-bearing constraints (not optional):**
- **Token floor.** Gate every comparison on `total_tokens`; a distribution from
  40 tokens is noise with confidence. Store the count.
- **Snapshot the basis with every verdict.** The top-N and population stats drift
  as the corpus grows, so persist the exact vocab + stats a linkage verdict used,
  or the verdict is not reproducible (operator-grade-evidence requirement).
- Incremental upsert (`ON CONFLICT DO UPDATE count = count + n`) is dialect SQL:
  concrete-backend override, mixin declares + NotImplementedError (CLAUDE.md §2.3
  Rule 1). Postgres-primary.

**Shape:** three tables (`actor_mfw_count`, `actor_mfw_profile`,
`locale_token_freq`), an event-driven ingest sensor, `eyenet mfw-backfill` +
`eyenet mfw-prune` CLIs, a Verifier comparator (the three distances), and an
analyst viz (per-actor MFW bar chart + inter-actor Delta heatmap). Calibrate
thresholds per-locale on the M5 grid; inherit N + Delta config from `poc-luar`.

## Promote graph to case (graph -> case "transliteration")

**Deferred until the Graph Explorer FE is finished.** Raised 2026-10-17.

**Vision:** one button on the graph map toolbar turns a saved investigation
graph (actors, groups, artifacts, personas, edges, notes) into a real EYENET
case. A crime board you cannot testify from is useless.

**Shape:** PROMOTION, not a live mirror. One-shot snapshot graph -> new case,
with a back-reference (`case.source_graph_id`) so the graph re-opens, but NO
bidirectional sync (conflict resolution is a tar pit). Mapping:
- node -> case entity association (LINK the existing row, never copy it)
- edge (kind + reason) -> documented case linkage
- inspector notes -> case annotations
- the saved graph -> attached as the visual exhibit
- the promote action -> an audit-chain entry (seeded from graph X by Y at T)

Modal asks the operator for: title, primary subject (dropdown of canvas
actors/personas), summary/hypothesis (freetext), which nodes to include
(default all), tier confirmation. Submit -> create case, associate entities,
document edges, copy notes, attach exhibit, write audit, "Open case." Re-promote
= new case by default; warn via the back-reference to avoid dupes.

**Three integrity rules (non-negotiable):**
1. A graph has NO narrative. Do the mechanical 80%, then STOP and ask the
   operator for title/subject/summary. Never auto-generate a case narrative
   from topology (manufacturing a conclusion the operator did not write).
2. Preserve provenance. OPERATOR-created nodes are hypotheses, not observed
   evidence; they must stay flagged as operator-asserted in the case.
3. No clearance laundering. Refuse nodes above the operator's clearance, or
   stamp the case at the highest tier present. Never silently downgrade tier.

**Before building:** read the case<->entity association model and the linkage
model (`create_case`, `transition_linkage`) first. Reuse the existing case
entity-association surface; do NOT invent a parallel "case subject" table.

## Sub-graphs (graphs within graphs) — Graph Explorer

**Deferred. Raised 2026-10-17.** Honors the RULE OF KOOL (bigger, cooler graphs)
AND is a real performance lever (render/layout a collapsed super-node instead of
its whole interior).

**Vision:** a graph node can BE another graph. Nest them arbitrarily:

```
LATAM threat-actor landscape  (top graph)
- Group A  -> actors A, B, C + their messages, posts, groups, ...   (a sub-graph)
- Group B  -> actors D, E, F + their messages, posts, threads, ...  (a sub-graph)
- ... ad absurdum
```

A super-node collapses an entire sub-graph to one node; expand to descend into it,
collapse to zoom back out. The top graph stays small and fast; the detail lives one
level down.

**Why it helps performance:** the big-node / layout cost is paid per visible node.
Collapsing a cluster to one super-node means cytoscape lays out/renders N super-nodes,
not the thousands inside them. Pairs with the existing HEAVY_NODE_COUNT budget + the
big-enrich warning.

**Shape to figure out when we build it:**
- Model: a saved graph that can reference other saved graphs as members (an
  `investigation_graph` node whose entity is itself a graph id). No entity-model
  change — it is a graph-of-graphs, built on the saved-graph tables.
- Cytoscape: compound nodes (parent/child) OR a collapse/expand that swaps a cluster
  for a synthetic super-node (cytoscape-expand-collapse ext, or hand-rolled). Decide
  which; compound nodes are native but fight fcose/dagre; swap-to-super-node keeps
  layouts simple.
- Collapse heuristics: auto-collapse by source/group/persona cluster; manual
  box-select -> "group into sub-graph".
- Enrichment across boundaries: expanding inside a sub-graph must not re-explode the
  parent; the big-enrich warning + per-sub-graph node budget apply.
- Save/restore: a sub-graph collapse state persists with the saved graph (and the
  localStorage draft).

## Incident nodes - follow-ups (core DONE 2026-10-18)

DONE: `message/thread/actor -> incidents` enrichments (synthesized red nodes from
IncidentTable); "Mark as incident" relabel dialog on message nodes (PUT
/v1/incidents/{id}/labels, reuses the triage machinery).

Remaining follow-ups:
- Incident nodes are SYNTHESIZED (not search-indexed), so a saved graph's incident
  node shows its id on reload (re-enrich to restore). Index incidents (incident_doc +
  indexer + emit on classify) if persistence is wanted - same pattern as persona/crew.
- Open an incident node -> its classifier scores / geo-victim country / severity in a
  detail panel (the detail modal already has a fallback slot).
- "Mark as incident" on a THREAD -> relabel its OP message (needs the OP message id;
  thread_summary.op_message_id has it).

## BUG: test_classify_end_to_end_when_model_present FAILS

`tests/unit/incidents/test_classifier.py::test_classify_end_to_end_when_model_present`
fails (pre-existing, from the in-flight mmBERT/incident-model work — NOT from graph/
enrichment changes). Triage + fix so the suite is fully green.

## Discord collector (not started; raised 2026-10-18)

CTI collection of threat-actor Discord guilds. Scope it incrementally: identity + token
storage first, then ONE read-only channel pull (prove token + fingerprint + rate limits),
then the Gateway for live. Don't build the whole thing before one GET /messages is 200.

**The API reality:**
- Bot API is useless (a bot must be INVITED to the guild; never happens on a target).
- Use the USER API (the client's own REST + Gateway) with a warmed account's USER TOKEN:
  - history: `GET /api/v9/channels/{channel_id}/messages?limit=100&before={snowflake}`
  - live: the Gateway WebSocket (MESSAGE_CREATE), same as the client.
- This is the Telegram-`.session` / forum-cookie-jar analogue: a warmed account, not a bot.

**Already solved (reuse existing tradecraft):**
- `ServiceBase` collector, plural from day one; identity = user token + UA + super-properties
  as source-prefixed TOML fields (`discord_user_token`, ... per [[feedback_identity_toml_source_prefix]]).
- Token stored OFF-network, encrypted at rest (like the Telegram `.session`; never on reads).
- Snowflake ids are timestamp-encoded -> before/after pagination drops into the forward-only
  cursor + backfill-command model (like [[project_telegram_backfill_forward_only]]).
- TLS/JA3 impersonation via curl-cffi already proven on the forum collector (httpx ClientHello
  is the Python tell) - Discord is behind Cloudflare, same playbook.
- Invisible presence instinct from the Matrix collector ([[feedback_matrix_collector_offline_only]]).
- Taxonomy fits: guild->channels->messages, Discord forum channel = category, threads = thread,
  posts = messages -> the monitored-group/category/thread/post display taxonomy already built.

**Be wary (the hard parts):**
- SELF-BOT BAN RISK: automating a user account violates Discord ToS; aggressive detection.
  Warmed throwaway accounts, human pacing, invisible status, burn-and-replace, keep spares.
- FINGERPRINTING: every request carries `X-Super-Properties` (base64 JSON: OS/browser/client
  build no.). UA <-> super-properties <-> account's origin client MUST match (same coupling as
  forum_user_agent <-> cookie-mint browser). Likely needs curl-cffi JA3 impersonation.
- RATE LIMITS: strict, per-route (`X-RateLimit-*`, 429 + retry_after) + a global bucket.
  Respect them or the account gets flagged (same windowing discipline as the forum evasion).
