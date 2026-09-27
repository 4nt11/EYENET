# EYENET — Docker deployment

Single-host `docker compose` stack: one image (`eyenet:base`), one command per
service, a NATS container, and a shared data volume. This is the primary path for
container deployments; the systemd/native templates in `../` remain for bare-metal.

## Layout

| File | Purpose |
|------|---------|
| `Dockerfile` | base runtime image — all core services |
| `Dockerfile.classifier` | base + M10 extraction toolchain (nsjail/tesseract) — **REQUIRES TUNING** |
| `Dockerfile.incidents` | base + ML runtime (torch/transformers) for the incident classifier |
| `compose.yaml` | the stack (core services + `classifier`/`incidents`/`collectors` profiles) |
| `env.example` | copy to `.env` and edit |
| `../../.dockerignore` | trims the build context (repo root) |

## Services

Core (start by default): `nats`, `api` (published, owns first-boot schema),
`graph`, `supervisor`, `anchor`, `sensor`, `engine`, `linker`, `verifier`.
Opt-in profiles: `classifier`, `incidents` (see setup below), `collectors`.

Workers `depends_on` the API being **healthy** — the API creates the SQLite
schema on first boot (`create_all`), so nothing races an empty DB.

## Quick start

```bash
cd deploy/docker
cp env.example .env                 # edit CORS origin etc.

# TLS: the API refuses an insecure non-loopback bind. Dev self-signed:
mkdir -p tls
openssl req -x509 -newkey ed25519 -nodes -days 365 \
    -keyout tls/key.pem -out tls/cert.pem -subj /CN=localhost

docker compose build
docker compose up -d                # core pipeline

# Bootstrap the first admin (creates schema + admin; password printed once):
docker compose run --rm api user create admin --role admin --generate

# Then, for the clearance surface, self-grant the grant-only scope:
docker compose run --rm api user scopes grant admin admin:clearance --as admin
```

API is then at `https://localhost:8443` (accept the self-signed cert). Point the
frontend's `VITE_EYENET_API` at it.

## Profiles

```bash
# Classifier (see caveat below):
docker compose --profile classifier up -d

# A collector for one identity (drop its session into the data volume first):
EYENET_IDENTITY=scout01 EYENET_COLLECTOR_TYPE=telegram \
    docker compose --profile collectors up -d collector
```

For several identities, copy the `collector` service in `compose.yaml`
(`collector-scout02`, ...) or drive it with `docker compose run`.

## Operate

```bash
docker compose ps
docker compose logs -f anchor          # signed audit/journal-head heartbeats
docker compose logs -f api
docker compose down                    # stop (data volume persists)
docker compose down -v                 # stop + WIPE data volume (destructive)
```

## Classifier caveat (REQUIRES TUNING)

`Dockerfile.classifier` is a **scaffold**, not a turnkey image. nsjail needs
`CLONE_NEWUSER` + its own seccomp, so the compose service runs with
`security_opt: seccomp=unconfined` + `cap_add: SYS_ADMIN` (least-bad for a single
host; tighten later). Before it classifies for real:

1. **Vendor `nsjail`** — it isn't in Debian repos. Put a prebuilt static binary at
   `deploy/docker/nsjail` (the Dockerfile COPYs it), or add a build stage.
2. **Pin the extract-venv deps** from the real extraction requirement set — the
   list in `Dockerfile.classifier` (`pymupdf`/`python-docx`/`presidio`/
   `pytesseract`/`pillow`) is the expected shape, not a verified pin.

The core stack is fully functional without the classifier — it's an opt-in profile
on purpose.

## Incident classifier setup (the one step beyond `up -d`)

The incident classifier detects threat-actor incidents (breach/leak/infostealer/
access-sale/actor-ops/tooling) on monitored-channel messages, batched off the bus. It's
the only service that needs more than `docker compose up -d`, because two things are
**not** in the image and **not** in git:

1. **The trained model** (~1.2GB — weights + tokenizer + `calibration.json`). It's
   sensitive (trained on real threat-actor data) and gitignored, so you provide it:

   ```bash
   # from the repo root — copy the trained model dir the bind-mount expects:
   cp -r dataset/mmbert-incident-ml deploy/docker/incident-model
   ```

   The dir is self-contained; the runtime loads it fully **offline** (no Hub download).

2. **The ML runtime** (torch/transformers) — a separate image (`Dockerfile.incidents`),
   GPU by default.

```bash
cd deploy/docker
# GPU (default — CUDA 12.8; ~12x faster batched than CPU on an RTX 5060):
docker compose build incident-classifier
docker compose --profile incidents up -d incident-classifier
```

Then it subscribes `raw.message.>`, stores incidents, and serves the triage feed:
`GET /v1/incidents` (poll), `GET /v1/stream/incidents` (SSE), and it publishes
`incident.detected` on the bus. Operators tune detection live via
`/v1/incident-rules` (RE2 → label; picked up within 30s, no redeploy).

**GPU vs CPU.** GPU is the default and is ~12x faster batched (≈590 vs ≈48 msgs/s on a
5060). The model shares the card with the stage-3 ollama LLM (8GB); if CUDA is present but
runs out of memory at load, the service **auto-falls-back to CPU** (logs
`incident.cuda_unavailable_fallback_cpu`) instead of crashing — no config needed. To run
CPU-only *proactively* (frees the GPU entirely; enough for small-operator live volume):

```bash
# CPU fallback: comment out the `deploy:` GPU block in compose.yaml, then:
EYENET_INCIDENT_DEVICE=cpu \
EYENET_TORCH_INDEX=https://download.pytorch.org/whl/cpu \
    docker compose build incident-classifier
EYENET_INCIDENT_DEVICE=cpu docker compose --profile incidents up -d incident-classifier
```

GPU requires the **nvidia container runtime** on the host. Scopes: users need
`read:incidents` (feed), `stream:incidents` (SSE), `admin:incident_rules` (manage rules)
— all in the admin baseline; analysts get read+stream, viewers get read.

## Notes

- **NATS** is core-only (no JetStream); SSE replay is served from storage. Not
  published to the host — internal to the compose network.
- **Data** lives in the `eyenet-data` named volume (`main.db`, `audit.db`, and the
  server keys under `jwt/` — JWT, exoneration, anchor, deployment_id). Back it up.
- **Full-Docker vs systemd**: the same `ExecStart` commands back both paths, so
  the `../` systemd templates and this compose stay in lockstep.
