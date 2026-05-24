# Live Smoke Test — Matrix Collector + Stylometric Sensor

Manual test. Not in CI. Run against a throwaway Matrix identity on a low-traffic test room.

The Matrix collector ALWAYS operates with `set_presence="offline"`. Your identity will appear offline to other room members. There is no operator knob to change this — it's a hard OPSEC rule. See `eyenet/collectors/matrix/real.py:_PRESENCE_OFFLINE`.

## Prerequisites

1. A Matrix account on any homeserver. The reference test identity is:
   - **Homeserver**: `https://element.unredacted.org`
   - **User**: `@leroyjenkins:unredacted.org`
   - **Password**: held out-of-band — do NOT commit it to the repo. Ask the operator.
2. The identity joined to at least one room with recent activity. Use a throwaway room you control.
3. An **access token** for that identity (see next section — the collector uses tokens, never passwords).
4. A second client (Element web/desktop, Cinny, …) signed in as a different account so you can post messages into the test room without echoing back to the collector.

## Discovering the homeserver URL

The Matrix `user_id` is `@<localpart>:<server_name>`. The `server_name` (the part after the colon) is NOT necessarily the API host — it's the identity domain. The actual API base URL is published at `https://<server_name>/.well-known/matrix/client`:

```bash
curl -s https://unredacted.org/.well-known/matrix/client | jq .
```

```json
{
  "m.homeserver": {
    "base_url": "https://matrix.unredacted.org"
  }
}
```

`matrix_homeserver_url` in `identities.toml` must be the `m.homeserver.base_url` value — `https://matrix.unredacted.org` in this case. NOT `https://element.unredacted.org` (that's the Element web client URL — different host).

If no `.well-known` is served, fall back to `https://<server_name>` directly. If even that 404s, ask the homeserver admin for the API host.

## Obtaining the access token

The collector does NOT log in with a password — it uses a pre-provisioned access token. Two ways to get one:

### Option A: Element web UI

1. Sign in as `@leroyjenkins:unredacted.org` at https://app.element.io with the homeserver set to `https://element.unredacted.org`.
2. Settings → Help & About → Advanced → click **Access Token** to reveal.
3. Copy the token. It looks like `syt_<base64>…`.
4. **Also note** the device ID shown alongside (e.g. `EYENET01`). You'll need it for the TOML.

### Option B: curl against the login endpoint

```bash
curl -s -X POST https://element.unredacted.org/_matrix/client/v3/login \
  -H 'Content-Type: application/json' \
  -d '{
    "type": "m.login.password",
    "identifier": {"type": "m.id.user", "user": "leroyjenkins"},
    "password": "<PASSWORD>",
    "device_id": "EYENET01",
    "initial_device_display_name": "EYENET smoke"
  }' | jq
```

Keep the `access_token` and `device_id` from the response. The token survives across restarts; you do NOT need to re-login on every smoke run.

> **OPSEC note:** the password is single-use here — only the access token goes into `identities.toml`. Treat the token like a password: it grants full account access. The file should land at `0600`, gitignored, age-encrypted at rest per PLAN §6.1.

## Verify the token + URL before launching the collector

One curl saves an hour. Run this with your token to confirm both the homeserver URL and the access token before plumbing them through `identities.toml`:

```bash
TOKEN="syt_paste_your_token_here"
curl -s -H "Authorization: Bearer $TOKEN" \
  https://matrix.unredacted.org/_matrix/client/v3/account/whoami | jq
```

Expected: `{"user_id": "@leroyjenkins:unredacted.org", "device_id": "EYENET01", "is_guest": false}`.

If you get HTML / a 404, the URL is wrong — go back to the `.well-known` step. If you get `{"errcode": "M_UNKNOWN_TOKEN"}`, the token is bad — generate a new one.

The collector itself does this same check on boot via `_verify_auth` and will refuse to enter `sync_forever` if it fails. That avoids the cryptic `Error validating response: 'next_batch' is a required property` loop you'd otherwise see.

## Setup

**1. Create the identities file:**

```toml
# ~/.config/eyenet/identities.toml  (or anywhere; pass --identities below)
[[identities]]
name             = "alpha_mx"
source           = "matrix"
cooldown_seconds = 0

matrix_homeserver_url = "https://matrix.unredacted.org"   # the .well-known base_url
matrix_user_id        = "@leroyjenkins:unredacted.org"
matrix_access_token   = "syt_…"           # from the step above
matrix_device_id      = "EYENET01"

# Optional: restrict to specific rooms. Accepts `!room_id:server` (canonical)
# or `#alias:server` (resolved at startup). Leave empty to monitor every room
# the identity is joined to.
matrix_monitor_rooms = ["#eyenet-smoke:unredacted.org"]
```

**Permissions:**

```bash
chmod 0600 ~/.config/eyenet/identities.toml
```

No session file. Matrix carries auth inside the TOML — the loader detects this via `_uses_session_file(SourceKind.MATRIX) == False` and does not enforce a `session_path` existence check.

## Run

Open two terminals.

**Terminal 1 — sensor:**

```bash
eyenet sensor --profile stylometric --memory-bus
```

**Terminal 2 — collector:**

```bash
eyenet collector \
  --type matrix \
  --identity alpha_mx \
  --identities ~/.config/eyenet/identities.toml \
  --memory-bus \
  --data-dir /tmp/eyenet_data_matrix
```

You should see structured log lines:

- `collector.ready` once on boot, with `instance_id`, `monitor_rooms` (resolved!-IDs), and identity name.
- `collector.room_resolved` for every `#alias:server` entry that got mapped to a canonical `!room_id:server`.
- `collector.ingested` per received text message.

From your second client, post a few messages into the test room. The collector should pick them up within ~1s of the homeserver's next sync delivery (sync timeout is 30s but messages arrive faster than that).

Leave both running for **5 minutes** while the test room receives traffic.

## Assertions

### 1. Messages ingested

```bash
sqlite3 /tmp/eyenet_data_matrix/messages.db \
  "SELECT count(*) FROM message;"
```

Expected: `> 0`.

```bash
sqlite3 /tmp/eyenet_data_matrix/messages.db \
  "SELECT evidence_ref, length_words FROM message LIMIT 5;"
```

Expected: every `evidence_ref` starts with `matrix:!`. Bodies are populated; `length_words` matches a `wc -w` on the body.

### 2. The collector is invisible to other clients

In your second Element/Cinny session, look at the test room's member list. `@leroyjenkins:unredacted.org` should appear **offline** even while the collector is actively running and ingesting. This is the OPSEC contract — `set_presence="offline"` is sent on every sync.

If the collector identity ever shows as **online** while the process is running, that is a serious bug. File it immediately.

### 3. Self-echoes are dropped

From the collector identity itself (if you can get into a third client signed in as `@leroyjenkins`), send a message into the monitored room. It should NOT appear in `messages.db` — the collector drops events where `sender == own_user_id`.

```bash
sqlite3 /tmp/eyenet_data_matrix/messages.db \
  "SELECT count(*) FROM message m JOIN actor a ON m.actor_id = a.id
   WHERE a.handle = '@leroyjenkins:unredacted.org';"
```

Expected: `0`.

### 4. At least one primitive fired

```bash
sqlite3 /tmp/eyenet_data_matrix/observations.db \
  "SELECT primitive_name, count(*) FROM observation GROUP BY primitive_name;"
```

Expected: at least `lexical.vocabulary_richness` and `stylometric.character_ngram_simhash` have non-zero rows. The MATTR / distinctive-vocab / spaCy-trio primitives require larger corpus windows; quiet rooms during the 5-minute window will skip those.

### 5. Audit chain integrity + Matrix-specific events

```bash
python - <<'EOF'
import sqlite3
conn = sqlite3.connect("/tmp/eyenet_data_matrix/audit.db")
rows = conn.execute(
    "SELECT id, prev_hash, self_hash, service, event FROM auditlog ORDER BY at"
).fetchall()
prev = "0" * 64
services = set()
events = set()
for row_id, prev_hash, self_hash, svc, ev in rows:
    assert prev_hash == prev, f"chain broken at {row_id}: expected {prev} got {prev_hash}"
    prev = self_hash
    services.add(svc)
    events.add(ev)
print(f"Audit chain intact — {len(rows)} entries")
print(f"Services seen: {sorted(services)}")
print(f"Events seen:   {sorted(events)}")
assert "collector.matrix" in services, "collector.matrix did not write audit"
assert "service.start" in events and "service.stop" in events
EOF
```

Expected:
- `Audit chain intact — N entries` with no assertion error.
- `collector.matrix` and `sensor` both in the services set.
- `service.start` and `service.stop` both in events.

### 6. `instance_id` matches the pinned formula

```bash
python -c "
from eyenet.contracts.collector import compute_instance_id
from eyenet.contracts.enums import SourceKind
print(compute_instance_id('alpha_mx', SourceKind.MATRIX))
"
```

For identity name `alpha_mx`, this MUST print `4ba08aaf`. Cross-check against the collector's startup log: `instance_id=4ba08aaf`. If they disagree, the formula has drifted — that breaks bus-subject filtering across hosts and is a load-bearing-constant regression.

### 7. No panic or crash logs

Scan both terminal outputs for `level=error`. Acceptable: transient `collector.client_close_failed` on shutdown if the homeserver TCP socket is already gone. Not acceptable: `primitive.error`, `collector.ingest_error`, `collector.sync_task_shutdown_error`.

## Troubleshooting

### `ValueError: matrix_homeserver_url=... did not respond to GET /account/whoami`

The collector tried `whoami` and the homeserver didn't answer with valid JSON. Almost always means the URL points at the wrong host (Element web vs API host, or the apex domain instead of the API host). Re-do the `.well-known` discovery step.

### `ValueError: matrix_access_token rejected by ...`

The homeserver returned a `WhoamiError` — token is expired, revoked, or never valid. Generate a new one. Note: tokens are tied to device IDs; if you re-login from Element on the same device, the previous token may be invalidated.

### `ValueError: matrix_user_id=... does not match the token's actual user_id=...`

The token is for a different account than the one in `matrix_user_id`. Either fix the TOML or generate a token for the right account.

### `Error validating response: 'next_batch' is a required property` (looping)

This used to be the symptom of any of the three failures above before `_verify_auth` was added. If you ever see it after these checks pass, it indicates an actual schema drift between matrix-nio and the homeserver — file a bug.

### `collector.room_resolve_failed alias=#foo:server error='unknown error'`

Possible causes (most → least common):
1. The alias doesn't exist on that homeserver.
2. The room exists but the identity isn't joined and the room directory is closed to non-members.
3. Federation between your homeserver and the alias's homeserver is broken.

Workaround: use the canonical `!room_id:server` form in `matrix_monitor_rooms` instead. Or join the room from Element first, then re-launch the collector.

## Teardown

```bash
# Shutdown both processes with Ctrl-C, then clean up:
rm -rf /tmp/eyenet_data_matrix
```

The access token in `identities.toml` survives the process exit. If you want to invalidate it, log out of the device from Element settings → Sessions → revoke `EYENET01`.

## Backfill (optional)

Pass `--backfill` to additionally page backwards through each monitored room's history at startup:

```bash
eyenet collector \
  --type matrix \
  --identity alpha_mx \
  --identities ~/.config/eyenet/identities.toml \
  --memory-bus \
  --data-dir /tmp/eyenet_data_matrix \
  --backfill
```

You'll see `collector.backfill_start` then `collector.backfill_done` per room. Live `sync_forever` runs in parallel — duplicate `evidence_ref`s are short-circuited by `MessageStore.put_message`.

Per-room cap is 1000 events by default (sanity stop for forgotten flags). `--backfill` **requires** `matrix_monitor_rooms` to be non-empty in the TOML — refusing the implicit "all joined rooms" case prevents an accidental fleet-wide scrape.

Note: backfill resumes from the latest sync token on every restart — no persisted cursor yet. Dedup via the `evidence_ref` UNIQUE constraint keeps it correct but means each restart re-paginates. Persisted resume tokens are deferred until a room large enough to feel it shows up.

## Known limitations (M7 scope)

- **Text-only.** `m.image`, `m.file`, and other event kinds are ignored at the callback level. `has_attachment=False` always. Attachment ingestion is a follow-up milestone.
- **No E2EE.** Encrypted rooms emit `MegolmEvent`, which the collector does not subscribe to. They are silently dropped. To monitor an encrypted room, M7+ work needs to wire `matrix-nio[e2e]` (libolm dep + per-identity key cache).
- **No reply graph.** `m.relates_to` is not parsed. `reply_to_platform_msgid` is always `None`. Telegram has this; Matrix does not yet.
- **One collector = one identity.** Same scoping rule as Telegram per PLAN §2.1 — to add a second Matrix identity, launch a second `eyenet collector` process with a different `--identity` and a separate entry in `identities.toml`. Distinct `instance_id`s emerge automatically from the pinned formula.
