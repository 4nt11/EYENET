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

## Collector control-plane vs data-plane are decoupled

The `CollectorTable` row (created via `POST /v1/collectors`, managed in the UI)
and the actual collector *process* are not linked. A collector process is
launched as `eyenet collector --identity <name>` (the compose `collector`
service) and claims an **identity by name** via the DB pool — it never references
a `collector_id`. So a UI-managed collector row and a running process are two
separate things: starting/stopping a row does not start/stop a process, and a
running process does not surface on its "matching" row (no heartbeat, groups=0).

**Shape when we fix it:** bind the process to its `collector_id` (pass
`--collector-id`, or have the process claim/register against the row), so the
row reflects the real process — heartbeat, resolved groups, restarts. This is
the prerequisite for the observed-state fix below.

## `observed_state` is bookkeeping, not liveness (UI shows a false "running")

`CollectorSupervisor.reconcile_collectors()` (`eyenet/services/collector_supervisor.py`)
just mirrors `observed_state` onto `desired_state` — clicking "start" in the UI
sets `desired=running` and the supervisor rubber-stamps `observed=running` **with
no process actually running**. The real liveness signal is the heartbeat, which
stays empty. Operators see "running" for a collector that ingests nothing.

**Shape when we fix it:** derive `observed_state`/liveness from a real heartbeat
(process → `record_collector_observed_state` + a heartbeat timestamp on its own
`collector_id`), and have the UI trust the heartbeat, not the mirrored state.
Depends on the control/data-plane binding above. Consider whether the supervisor
should actually *launch* the data plane (spawn the collector) rather than only
reconcile a flag.

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
