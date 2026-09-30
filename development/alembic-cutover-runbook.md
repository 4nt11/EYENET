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

## Steps (run on the deploy host)

**1. Quiesce writers.** Stop the stack so nothing writes mid-cutover:
```
docker compose -f deploy/docker/compose.yaml down
```

**2. Back up the volume.** Non-negotiable. Snapshot both DBs out of the volume:
```
docker run --rm -v eyenet-data:/data -v "$PWD":/backup alpine \
  sh -c 'cp /data/main.db /backup/main.db.pre-alembic && cp /data/audit.db /backup/audit.db.pre-alembic'
```
Verify `main.db.pre-alembic` / `audit.db.pre-alembic` exist and are non-zero
before continuing. Keep them until the migrated stack has run clean for a while.

**3. Build the new image** (carries the migration tree + alembic dep):
```
docker compose -f deploy/docker/compose.yaml build api
```

**4. Drift check — MUST be empty before you stamp.** A one-off container runs
the same `compare_metadata` guard the test uses, against the LIVE DBs:
```
docker compose -f deploy/docker/compose.yaml run --rm --no-deps \
  -v eyenet-data:/var/lib/eyenet api \
  python -m eyenet.storage.sqlite_repo._drift_check /var/lib/eyenet
```
Expected: `main drift: 0` and `audit drift: 0`. If either is non-zero, the live
schema differs from the models (e.g. a table the models added after this DB was
last booted). Resolve that first — do NOT stamp over a mismatch; a stamp that
lies is worse than no Alembic. (Bring the live schema up to the models with the
pre-cutover code, then re-check.)

**5. Stamp both DBs at the baseline:**
```
docker compose -f deploy/docker/compose.yaml run --rm --no-deps \
  -v eyenet-data:/var/lib/eyenet api \
  alembic -x data_dir=/var/lib/eyenet stamp 0001_baseline
```
`env.py` loops both engines, so this writes `alembic_version = 0001_baseline`
into main.db AND audit.db.

**6. Boot the migrated stack:**
```
docker compose -f deploy/docker/compose.yaml up -d
```
On boot the constructor runs `upgrade_to_head`; both DBs are already at head, so
it is a no-op. Confirm `/v1/healthz` is green and spot-check the incident feed.

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
