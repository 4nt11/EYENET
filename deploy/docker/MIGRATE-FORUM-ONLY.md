# Forum-only migration: dev to prod

One-time runbook for seeding the prod VM with FORUM (and operator-curated
OPERATOR) data only, dropping Telegram + Discord. The dev DB is **never**
touched: all surgery happens on a disposable staging postgres on this box.

**Why not a full dump:** Telegram sessions on dev are tied to a personal
account that cannot move to prod. Fresh bought accounts on prod are not
members of the monitored channels, so TG data on prod would be orphaned.
Discord: same reasoning. Forums: cookie jar + crawl cursors come across
cleanly. Operator curation (crews, personas, investigations): comes across.

## 0. Prerequisites

- Dev compose stack is up (it is right now).
- `xmart-eyenet` is SSH-reachable (confirmed: `ssh xmart-eyenet whoami`).
- The prod VM has `~/EYENET` checked out at `v1.1.0` and a working
  `deploy/docker/.env` with its own `EYENET_PG_PASSWORD` +
  `EYENET_CLICKHOUSE_PASSWORD` (generated separately).
- Prod has NOT yet run `deploy.sh deploy`. We want postgres bootstrapped
  by compose into an empty state we can restore into.

## 1. Quiesce writers on dev

Only the workers that write to the DB need stopping; keep postgres up so
we can dump.

```bash
cd ~/Projects/EYENET/deploy/docker
docker compose stop \
  supervisor sensor engine linker verifier discovery graph geo \
  search-indexer stealer-processor
```

## 2. Dump dev to `/tmp/migrate/`

```bash
mkdir -p /tmp/migrate
cd ~/Projects/EYENET/deploy/docker

# Both DBs, custom format for selective restore.
docker compose exec -T postgres pg_dump -U eyenet -Fc eyenet       > /tmp/migrate/eyenet-full.dump
docker compose exec -T postgres pg_dump -U eyenet -Fc eyenet_audit > /tmp/migrate/eyenet_audit.dump
```

Audit is NOT filtered (it is a hash-chained operator-action log and must
stay intact).

## 3. Stage: spin up a disposable postgres on port 54320

```bash
docker run -d --rm --name eyenet-stage \
  -e POSTGRES_PASSWORD=stage \
  -e POSTGRES_USER=eyenet \
  -e POSTGRES_DB=eyenet \
  -p 127.0.0.1:54320:5432 \
  postgres:16.15-alpine

# Wait until it is ready (a few seconds)
until docker exec eyenet-stage pg_isready -U eyenet -q; do sleep 1; done

# Restore the FULL dev dump into staging.
docker cp /tmp/migrate/eyenet-full.dump eyenet-stage:/tmp/full.dump
docker exec eyenet-stage pg_restore -U eyenet -d eyenet \
  --clean --if-exists --no-owner /tmp/full.dump
```

Ignore "role does not exist" warnings. `--no-owner` strips those.

## 4. Filter staging to FORUM + OPERATOR only

```bash
docker cp forum-only-filter.sql eyenet-stage:/tmp/filter.sql
docker exec -i eyenet-stage psql -U eyenet -d eyenet -f /tmp/filter.sql
```

The final two blocks print sanity counts. The first should show ALL
ZEROES, the second shows the filtered shape (expect `source` = 4 FORUM + 1
OPERATOR, message count greater than 0, actor/group counts reasonable).

**Stop and read those numbers.** If anything is non-zero in the orphan
check, something in the filter missed a table. Fix the SQL, redo steps
3-4, do not ship.

## 5. Re-dump the cleaned staging DB

```bash
docker exec eyenet-stage pg_dump -U eyenet -Fc eyenet > /tmp/migrate/eyenet-forum-only.dump
```

## 6. Bundle the volume: only FORUM identity blobs + the fernet key

The identity-blob filenames are opaque UUIDs. Query the FORUM `session_path`
basenames from the (unfiltered) dev DB, then tar only those plus the
fernet key.

```bash
cd ~/Projects/EYENET/deploy/docker

# Extract the basenames (uuid.enc) of blobs tied to FORUM identities.
docker compose exec -T postgres psql -U eyenet -d eyenet -tAc \
  "SELECT regexp_replace(i.session_path, '^.*/', '')
     FROM identity i JOIN source s ON s.id = i.source_id
    WHERE s.kind = 'FORUM';" \
  | sed 's|^|./identities/|' > /tmp/migrate/keep-blobs.txt

# Include the key + jwt dir + any non-identity state (stealer-work, caches, etc).
cat >> /tmp/migrate/keep-blobs.txt <<'EOF'
./jwt
./jwt/session_fernet.key
EOF

# Any other top-level dirs in /var/lib/eyenet that are NOT identities/
# or jwt/ should also travel. Enumerate them from the volume:
docker run --rm -v docker_eyenet-data:/v alpine sh -c \
  "find /v -mindepth 1 -maxdepth 1 -not -name identities -not -name jwt -printf './%f\n'" \
  >> /tmp/migrate/keep-blobs.txt

# Tar it, using the keep-list.
docker run --rm -v docker_eyenet-data:/v -v /tmp/migrate:/out alpine \
  tar czf /out/eyenet-data.tgz -C /v --files-from=/out/keep-blobs.txt
```

`keep-blobs.txt` is a human-readable artifact. Open it and eyeball it
before the tar. You should see ~5 `./identities/{uuid}.enc` lines plus
`./jwt/...` plus any ClickHouse cache / attachment dirs.

## 7. Ship to prod

```bash
rsync -avP \
  /tmp/migrate/eyenet-forum-only.dump \
  /tmp/migrate/eyenet_audit.dump \
  /tmp/migrate/eyenet-data.tgz \
  xmart-eyenet:/tmp/migrate/
```

## 8. Restore on prod

On `xmart-eyenet`:

```bash
cd ~/EYENET/deploy/docker

# Bring up postgres FIRST, by itself, so we can restore before the app sees empty tables.
docker compose -f compose.yaml -f compose.prod.lite.yaml --profile stealer up -d postgres
until docker compose exec -T postgres pg_isready -U eyenet -q; do sleep 1; done

# Restore the volume BEFORE anything boots. The volume name is project-prefixed
# (confirm with `docker volume ls | grep eyenet-data`).
# NOTE: the --files-from keep-list on step 6 only names FILES, so tar recreates
# the parent dirs (identities/, jwt/) with the extracting process's defaults
# (root:root inside rootless alpine). The eyenet container runs as uid 10001
# and cannot write to a root-owned dir -> api 500s on tdata upload. Chown
# everything in one go here so the next identity provisioning works.
docker run --rm -v docker_eyenet-data:/v -v /tmp/migrate:/in alpine \
  sh -c 'cd /v && tar xzf /in/eyenet-data.tgz && chown -R 10001:10001 /v'

# Restore both DBs. The dumps carry schema@head, so compose's boot
# upgrade_to_head is a no-op.
cat /tmp/migrate/eyenet-forum-only.dump | \
  docker compose exec -T postgres pg_restore -U eyenet -d eyenet \
    --clean --if-exists --no-owner

cat /tmp/migrate/eyenet_audit.dump | \
  docker compose exec -T postgres pg_restore -U eyenet -d eyenet_audit \
    --clean --if-exists --no-owner

# Sanity:
docker compose exec -T postgres psql -U eyenet -d eyenet -c \
  "SELECT kind, count(*) FROM source GROUP BY kind;"
# Expect: FORUM 4, OPERATOR 1.  No TELEGRAM, no DISCORD.
```

## 9. First real deploy

```bash
# Still on prod:
EYENET_DOMAIN=your.domain EYENET_ACME_EMAIL=you@your.domain \
  deploy/docker/deploy.sh deploy
```

Forum collectors should boot, open their cookie jars (decrypted with the
migrated `session_fernet.key`), and resume crawling from the migrated
`forum_crawl_cursor` positions.

## 10. Teardown on dev

```bash
# Nuke staging container (data gone with it).
docker stop eyenet-stage

# Restart dev workers.
cd ~/Projects/EYENET/deploy/docker
docker compose up -d

# Keep /tmp/migrate around until prod is verified; then rm -rf.
```

## Known gotchas

- **DISCORD is being dropped** along with its 1 source. If that was wrong,
  edit `forum-only-filter.sql` line 26 to `IN ('FORUM','OPERATOR','DISCORD')`
  AND include DISCORD identities in the blob keep-list in step 6.
- **persona.member_actor_ids is JSON**. It may contain IDs of deleted
  (TG/Discord) actors. The filter deletes `persona_membership` rows but
  does not rewrite the JSON. Harmless (forward-only cheap view per model
  comment), rebuilds on next persona edit.
- **Documents are kept whole**. The document pipeline does not FK to
  source. If some of your docs were generated from TG messages the facts
  stay as-is.
- **Prod's `jwt/session_fernet.key` came from dev**, so prod can decrypt
  dev-encrypted forum sessions. The old `_session_key.py`
  auto-generate-if-missing behavior still applies on prod; if you ever
  wipe the volume before the app boots, it will mint a fresh key and
  forum sessions become permanently undecryptable. Back up this key file
  to KeePassXC along with the `.env`.
