# Alembic cutover runbook — bringing the LIVE operating DB under migrations

The v0.1.0 baseline (`0001_baseline`) lands with this branch. Fresh DBs now boot
via `alembic upgrade head` (create_all is retired). The **existing operating DB**
(the `eyenet-data` docker volume — the ~3k-thread DarkForums corpus) must be
brought under Alembic **once**, by hand, before the new image runs against it.

> The operating DB is irreplaceable. Every step below is non-destructive.
> `stamp` writes only the `alembic_version` bookkeeping table; it never touches
> your data. Do NOT `rm` anything. Do NOT run `upgrade` before you have stamped.

## Why stamp, not upgrade

The live DB already has every table (built by the old `create_all`) but no
`alembic_version` row. `alembic stamp 0001_baseline` marks it as "already at the
baseline" WITHOUT re-running DDL. If you instead let the app `upgrade` an
unstamped populated DB, Alembic would replay the baseline — it happens to be a
near no-op (`create_all(checkfirst=True)` + `IF NOT EXISTS` raw DDL) — but do not
rely on that. Stamp first; then the version tables reflect reality and every
future revision applies cleanly.

> ## ⚠️ THE FOOTGUN (learned the hard way, 2026-09-30)
> NEVER open the live volume DB with any SQLite tool (drift-check, alembic,
> sqlite3) after `docker compose down`. A non-graceful stop leaves a large
> uncheckpointed `-wal`; opening that crash-inconsistent state with a fresh
> connection can TRUNCATE `main.db`/`audit.db` to an empty 4096-byte stub. It
> did, once — recovered only because the VACUUM'd backup existed.
> The rule: **operate on a VACUUM'd snapshot copy, then copy the clean, stamped
> file back into the volume. Never run a tool against the live files in place.**

## Steps (run on the deploy host)

**1. Quiesce writers.** Stop the stack so nothing writes mid-cutover:
```
docker compose -f deploy/docker/compose.yaml down
```

**2. Consistent backup via `VACUUM INTO` (NOT `cp`).** A plain `cp` of `main.db`
misses the `-wal` (which can hold hundreds of MB of the newest data) and can
copy a torn page mid-write. `VACUUM INTO` folds the WAL in and writes a clean,
consistent, WAL-free single file. Do it while the stack is still up, or with a
one-off container after down:
```
docker run --rm -v eyenet-data:/var/lib/eyenet -v "$PWD":/backup --entrypoint python eyenet:base -c "
import sqlite3
for n in ('main','audit'):
    c=sqlite3.connect('/var/lib/eyenet/%s.db'%n)
    c.execute(\"VACUUM INTO '/backup/%s.db.pre-alembic'\"%n); c.close()
    print(n,'backed up')"
```
Verify both `.pre-alembic` files are non-zero and `PRAGMA integrity_check` = ok.
Keep them until the migrated stack has run clean for a while. **These backups
are the recovery anchor — never operate on them; work on copies.**

**3. Build the new image** (carries the migration tree + alembic dep):
```
docker compose -f deploy/docker/compose.yaml build api
```

**4. Drift-check + stamp a COPY of the backup — never the live DB.** Copy the
VACUUM'd backup to a scratch dir, drift-check it, and stamp it there:
```
mkdir -p /tmp/cutover && cp "$PWD"/main.db.pre-alembic /tmp/cutover/main.db && cp "$PWD"/audit.db.pre-alembic /tmp/cutover/audit.db
docker run --rm -v /tmp/cutover:/work --entrypoint python eyenet:base -m eyenet.storage.sqlite_repo._drift_check /work
```
Expected `main drift: 0` and `audit drift: 0`. If non-zero, the models differ
from this DB (e.g. a column the models widened, or an additive table) — resolve
that first; a stamp that lies is worse than no Alembic. Then stamp the copy
(programmatic form — no alembic.ini in the image):
```
docker run --rm -v /tmp/cutover:/work --entrypoint python eyenet:base -c "
from pathlib import Path
from alembic import command
from alembic.config import Config
from eyenet.storage.sqlite_repo.database import _MIGRATIONS_DIR, get_sync_engine
cfg=Config(); cfg.set_main_option('script_location', str(_MIGRATIONS_DIR))
cfg.attributes['engines']={'main':get_sync_engine(Path('/work/main.db')),'audit':get_sync_engine(Path('/work/audit.db'))}
command.stamp(cfg,'0001_baseline'); print('stamped')"
```

**5. Swap the clean, stamped copy into the volume** (replacing the live files;
clear any stale `-wal`/`-shm`; keep `eyenet` ownership):
```
docker run --rm -v eyenet-data:/var/lib/eyenet -v /tmp/cutover:/work:ro --entrypoint sh eyenet:base -c '
rm -f /var/lib/eyenet/*.db-wal /var/lib/eyenet/*.db-shm
cp /work/main.db /var/lib/eyenet/main.db
cp /work/audit.db /var/lib/eyenet/audit.db'
```
The container runs as `eyenet`, so the copies stay `eyenet`-owned. Verify
read-only (`mode=ro`) that both files carry `alembic_version = 0001_baseline`
and are not 4096 bytes.

**6. Boot the migrated stack:**
```
docker compose -f deploy/docker/compose.yaml --profile incidents up -d
```
On boot the constructor runs `upgrade_to_head`; the clean file is already at
head, so it is a no-op (and a clean WAL-free file opens safely). Confirm
`/v1/healthz` and `/v1/readyz` are 200 and spot-check the incident feed.

## From here on

A schema change is a revision, authored from the repo root against a scratch
`data_dir`:
```
alembic revision --autogenerate -m "add foo" -x data_dir=data
alembic upgrade head -x data_dir=data     # apply to your dev DB
```
Review the generated revision (batch mode is on for SQLite ALTERs). Deploy the
new image; the stack applies pending revisions on boot. On a large table an ALTER
is a copy-and-move — check the migration and the volume's free space first.
