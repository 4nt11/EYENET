# EYENET API — operations

Observability artifacts for the M9.6 metrics/tracing surface (API_PLAN §11.7–§11.10).

| File | Purpose |
|---|---|
| `alerts/eyenet-api.rules.yml` | Prometheus alerting rules (audit-integrity, availability, 5xx, SSE). |
| `dashboards/eyenet-api.json` | Grafana dashboard (import → pick your Prometheus datasource). |
| `otel-collector.sample.yaml` | OTel Collector with tail sampling (§11.6) + Prometheus export. |

## Turning monitoring on

Both exposition surfaces are **off by default** (§11.7.1) — a deployment that
hasn't deliberately enabled monitoring leaks no label-cardinality recon.

| Surface | Env var | Notes |
|---|---|---|
| Prometheus scrape `/v1/metrics` | `EYENET_API_METRICS_ENABLED=1` | scope-gated (`read:metrics`); 404 when off |
| OTLP push (traces + metrics) | `EYENET_OTEL_ENDPOINT=http://collector:4317` | any OTLP backend |
| Disable tracing entirely | `EYENET_TRACING_DISABLED=1` | logging still configured |

## Prometheus scrape — least-privilege PAT

`/v1/metrics` is never anonymous. Scrape it with a **Personal Access Token
scoped to only `read:metrics`** — not a dedicated user. Mint it from the
console **System → Auth & tokens → Mint token** (an admin already holds
`read:metrics`; the PAT carries only that one scope, so a leaked scrape
credential exposes metric values and nothing else — no evidence, no writes).
The full token is shown ONCE at mint time; copy it then.

**Docker stack** (`deploy/docker/`, `--profile observability`): the Prometheus +
Grafana services are already wired — Prometheus scrapes `https://api:8443/v1/metrics`
with the PAT, loads `alerts/eyenet-api.rules.yml`, and Grafana auto-provisions a
Prometheus datasource + the dashboard below. One-time setup:

```bash
cd deploy/docker
cp observability/eyenet.pat.example observability/eyenet.pat
# paste the console-minted read:metrics PAT into observability/eyenet.pat, then:
chmod 644 observability/eyenet.pat          # Prometheus runs non-root; it must read the file
docker compose --profile observability up -d prometheus grafana
```

Grafana is on `:3000` (admin / `EYENET_GRAFANA_PASSWORD`, default `admin`); the
Prometheus datasource + the dashboard below are auto-provisioned. To also ship
**traces** (OTel collector + Tempo), set `EYENET_OTEL_ENDPOINT=http://otel-collector:4317`
(in `.env` or inline), rebuild `eyenet:base`, and bring up the full profile:
`docker compose --profile observability up -d` (this recreates the app services
so they export spans).

**Standalone Prometheus** (HTTP/2 + TLS are mandatory, §12.1 — target is `https`):

```yaml
scrape_configs:
  - job_name: eyenet-api
    scheme: https
    metrics_path: /v1/metrics
    tls_config:
      insecure_skip_verify: true   # self-signed cert; swap a real CA to verify
    authorization:
      type: Bearer
      credentials_file: /etc/prometheus/eyenet.pat   # the read:metrics PAT
    static_configs:
      - targets: ["eyenet-api.internal:8765"]

rule_files:
  - /etc/prometheus/rules/eyenet-api.rules.yml
```

## Cardinality discipline (§11.7.3)

The Prometheus exposition carries **only bounded labels** — no per-user,
per-request, or per-target id. Per-user analytics belong on OTLP, never in
Prometheus. Enforced in `eyenet/telemetry/metrics.py` via per-instrument View
allow-lists; a new metric must declare its bounded label set there.
