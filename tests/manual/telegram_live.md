# Live Smoke Test — Telegram Collector + Stylometric Sensor

Manual test. Not in CI. Run against a throwaway Telegram identity on a low-traffic test channel.

## Prerequisites

1. A Telegram account you own and don't care about — create a throwaway if needed.
2. A Telegram API key pair (`api_id` + `api_hash`) from https://my.telegram.org.
3. The identity session file must already exist (first run will prompt for your phone number and OTP).
4. The identity joined to at least one channel or group with recent activity.

## Setup

**1. Create the identities file:**

```toml
# ~/.config/eyenet/identities.toml  (or anywhere; pass --identities below)
[[identities]]
name          = "tg_smoke"
source        = "telegram"
# session_path omitted → defaults to ~/.local/share/eyenet/sessions/tg_smoke
cooldown_seconds = 0
telegram_api_id   = 12345678          # your api_id
telegram_api_hash = "your_api_hash"   # your api_hash

# Optional: restrict to specific channels/groups.
# Accepts @username strings or numeric chat IDs (as strings).
# Leave empty to monitor ALL dialogs this identity is in.
monitor_groups = ["@my_test_channel", "-1001234567890"]
```

**2. Authenticate the session (first run only):**

The CLI handles this automatically — `eyenet collector-run --type telegram` will prompt for
your phone number and OTP if the session file is absent, then continue into the collector.
No manual bootstrap step needed.

## Run

Open two terminals.

**Terminal 1 — sensor:**

```bash
eyenet sensor --profile stylometric --memory-bus
```

**Terminal 2 — collector:**

```bash
eyenet collector \
  --type telegram \
  --identity tg_smoke \
  --identities ~/.config/eyenet/identities.toml \
  --memory-bus
```

Both processes emit structured logs to stdout. On a TTY they render as human-readable lines;
redirect to a file if you want raw JSON.

Leave both running for **5 minutes** while messages arrive in any joined channel.

## Assertions

### 1. Messages ingested

```bash
sqlite3 /tmp/eyenet_data/messages.db \
  "SELECT count(*) FROM message;"
```

Expected: `> 0`

### 2. At least one primitive fired per actor

```bash
sqlite3 /tmp/eyenet_data/observations.db \
  "SELECT primitive_name, count(*) FROM observation GROUP BY primitive_name;"
```

Expected: at least `lexical.vocabulary_richness` and `stylometric.character_ngram_simhash` have non-zero rows. The other two primitives require larger corpus windows (≥30 messages or ≥50 messages per actor) so they may be 0 if the channel is quiet.

### 3. Audit chain integrity

```bash
python - <<'EOF'
import sqlite3, json
conn = sqlite3.connect("/tmp/eyenet_data/audit.db")
rows = conn.execute(
    "SELECT id, prev_hash, self_hash FROM audit_log ORDER BY seq"
).fetchall()
prev = "0" * 64
for row_id, prev_hash, self_hash in rows:
    assert prev_hash == prev, f"chain broken at {row_id}: expected {prev} got {prev_hash}"
    prev = self_hash
print(f"Audit chain intact — {len(rows)} entries")
EOF
```

Expected: `Audit chain intact — N entries` with no assertion errors.

### 4. Evidence-access audit events exist

```bash
sqlite3 /tmp/eyenet_data/audit.db \
  "SELECT count(*) FROM audit_log WHERE event = 'evidence_access';"
```

Expected: `> 0` (one per sensor dispatch that reached body dereference).

### 5. No panic or crash logs

Scan both terminal outputs for `level=error`. The only acceptable errors are transient network blips from Telethon (flood wait, timeout). A `primitive.error` line indicates a primitive bug — capture and file.

## Teardown

```bash
# Shutdown both processes with Ctrl-C, then clean up:
rm -rf /tmp/eyenet_smoke /tmp/eyenet_data
```

## Known limitations

- MATTR and `distinctive_vocabulary_signature` require ≥100 tokens and ≥50 messages per actor respectively. Low-traffic channels during the 5-minute window will skip these.
- No multi-identity test here — that's M2.5 (`test_two_collectors_one_sensor.py` extended).
- `storage_uri` is `NULL` on all attachments — binary download is post-v0.
