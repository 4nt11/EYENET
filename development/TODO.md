# TODO

Deferred work, captured so it isn't lost. Not in priority order.

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
