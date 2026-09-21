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

`/v1/metrics` is never anonymous. Run Prometheus as a service-account
`SystemUser` holding a PAT with **only** `read:metrics`:

```bash
# One-time: create the scrape account and mint a read:metrics-only PAT.
eyenet user create --username prometheus-scrape --role viewer
eyenet token mint --username prometheus-scrape --scopes read:metrics --name prom > prom.pat
```

Then in `prometheus.yml` — note HTTP/2 + TLS are mandatory (§12.1), so the
scrape target is `https` and h2:

```yaml
scrape_configs:
  - job_name: eyenet-api
    scheme: https
    metrics_path: /v1/metrics
    authorization:
      type: Bearer
      credentials_file: /etc/prometheus/eyenet.pat   # the read:metrics PAT
    static_configs:
      - targets: ["eyenet-api.internal:8765"]

rule_files:
  - /etc/prometheus/rules/eyenet-api.rules.yml
```

The PAT holds `read:metrics` and nothing else: a leaked scrape credential
exposes metric values only — no evidence, no writes.

## Cardinality discipline (§11.7.3)

The Prometheus exposition carries **only bounded labels** — no per-user,
per-request, or per-target id. Per-user analytics belong on OTLP, never in
Prometheus. Enforced in `eyenet/telemetry/metrics.py` via per-instrument View
allow-lists; a new metric must declare its bounded label set there.
