# EYENET — Testing, Quality & Hooks (v0)

Companion to PLAN.md §7. This document defines the **toolchain**, the **pytest marker taxonomy**, and the **git hook stages** so the right tests run at the right time and the heavy stuff doesn't run on every save.

---

## 1. Toolchain (locked)

```toml
# pyproject.toml — [project.optional-dependencies].dev (sketch)
dev = [
  # runtime test
  "pytest>=8",
  "pytest-asyncio",
  "pytest-cov",
  "pytest-xdist",
  "pytest-timeout",
  "pytest-randomly",
  "pytest-benchmark",
  "hypothesis",
  "hypothesis-jsonschema",
  "syrupy",
  "polyfactory",
  "dirty-equals",
  "freezegun",
  "respx",
  "testcontainers[nats]",

  # load
  "locust",

  # static / sec
  "mypy",
  "ruff",
  "bandit",
  "deptry",
  "pip-audit",
  "detect-secrets",

  # orchestration — NO pre-commit framework; we use raw git hooks (see §5)
]

deferred = [
  "schemathesis",   # earned when Graph API has OpenAPI
  "mutmut",         # earned when primitive suite is stable
]
```

---

## 2. Pytest marker taxonomy

**Without markers we'll be running schemathesis on every save.** Each test gets exactly one *speed* marker (`unit` / `integration` / `e2e`) and zero-or-more *category* markers.

```ini
# pyproject.toml — [tool.pytest.ini_options]
markers = [
  # speed — exactly one per test
  "unit: fast, no I/O, no network, no DB. Default selection.",
  "integration: in-memory bus, in-memory or temp-file SQLite. No external processes.",
  "e2e: spawns real NATS / real services. Requires testcontainers. Slow.",

  # category — zero or more
  "contract: CDD contract test. Property-based or schema round-trip.",
  "calibration: stylometric AUC / discrimination tests. Needs labeled corpus.",
  "benchmark: pytest-benchmark perf assertion. Tracked over time.",
  "schema: schemathesis HTTP API fuzzing. Needs running service.",
  "load: locust load test (run via locust CLI, not pytest).",
  "slow: tests over 5s wall-clock. Catch-all for anything that needs to be opt-in.",
  "primitive: belongs to the BEHAVE-TEXT primitive suite. Tag with name in id.",
  "telegram: requires Telegram fixture / TDLib bind. Skipped without env flag.",
  "needs_pool: requires identity-pool fixture. Skipped without env flag.",
]
addopts = [
  "-ra",
  "--strict-markers",            # unknown marker = ERROR, not warning
  "--strict-config",
  "-m", "unit or contract",      # default selection is fast
  "--cov=eyenet",
  "--cov-report=term-missing",
  "--cov-fail-under=80",
  "--timeout=30",
]
testpaths = ["tests"]
```

### Selecting subsets

| Goal | Command |
|---|---|
| Default (commit hook) | `pytest` (runs `unit or contract`) |
| Full pre-push | `pytest -m "unit or integration or contract"` |
| E2E suite | `pytest -m e2e` |
| Calibration sweep | `pytest -m calibration --no-cov` |
| Single primitive | `pytest -m "primitive" -k function_word_top50` |
| Benchmarks | `pytest -m benchmark --benchmark-only` |
| Schemathesis (when API exists) | `pytest -m schema` |
| Everything (CI nightly) | `pytest -m ""` |

### Marker discipline

- `--strict-markers` makes typos errors. No silent miscategorization.
- `xfail(strict=True)` is the CDD pattern: write the contract test first, decorate with `@pytest.mark.xfail(strict=True, reason="impl pending")`, the build is green; when the impl lands and the test passes, strict mode flips the build red until the marker is removed. Forces the loop closed.

---

## 3. Coverage policy

- **Floor:** **95% global** (`--cov-fail-under=95`). Enforced **on every commit** via the pre-commit hook. Below 95% → commit refused.
- **Coverage delta:** any commit that *lowers* the previous coverage figure is refused regardless of absolute number. The pre-commit hook compares against the last committed coverage figure stored in `.coverage-baseline` (committed JSON: `{"line_rate": 0.9612, "ts": "..."}`). New code must be tested.
- **Per-package floors** (enforced same way, via `coverage` config):
  - `eyenet/contracts/` → **100%**. These ARE the spec.
  - `eyenet/sensor/primitives/` → **98%**. 20+ primitives, each needs golden + edge inputs.
  - `eyenet/services/` → 95%.
  - `eyenet/cli/` → 90%.
- Bypass for genuine emergencies: `git commit --no-verify` is allowed but the pre-push hook re-runs the gate, so the bypass survives only for local WIP commits — it cannot reach Gitea.

---

## 4. Static stages — what runs when

| Stage | Tools | Time budget |
|---|---|---|
| pre-commit | `ruff format`, `ruff check`, `mypy --strict` (changed files), `bandit` (changed files), `detect-secrets`, `deptry`, `pytest -m "unit or contract"` **with coverage** (≥95% + no delta drop) | < 30s |
| pre-push | full `pytest -m "unit or integration or contract"`, `mypy --strict` (full), `pip-audit`, coverage gate again | < 2 min |
| Gitea Actions on PR | everything pre-push + `pytest -m e2e`, coverage upload, benchmark regression check | < 10 min |
| Gitea Actions nightly | `pytest -m ""` (incl. calibration), mutation tests when added, full pip-audit + bandit | unbounded |

---

## 5. Git hooks — raw bash, repo-tracked

We do **NOT** use the `pre-commit` Python framework. Hooks are plain bash scripts kept in `.githooks/` (committed to the repo) and activated by:

```bash
git config core.hooksPath .githooks
```

This one-liner lives in the project's `Makefile` / `bootstrap.sh` so a fresh clone wires its own hooks without touching `.git/hooks/` directly. `.git/hooks/` is per-clone and not version-controlled — `.githooks/` is the repo-tracked source of truth.

### 5.1 Layout

```
.githooks/
├── pre-commit          # bash — fast checks, < 30s
├── pre-push            # bash — full local gate, < 2 min
├── commit-msg          # optional — conventional-commit format check
└── lib/
    ├── common.sh       # color, logging, abort helpers
    └── coverage.sh     # parses coverage.json, compares to .coverage-baseline
```

### 5.2 `.githooks/pre-commit`

```bash
#!/usr/bin/env bash
set -euo pipefail
. "$(dirname "$0")/lib/common.sh"

# Only act on files staged in this commit.
mapfile -t STAGED < <(git diff --cached --name-only --diff-filter=ACMR)
PY_STAGED=()
for f in "${STAGED[@]:-}"; do
  [[ "$f" == *.py ]] && PY_STAGED+=("$f")
done

step "ruff format (staged)"
[[ ${#PY_STAGED[@]} -gt 0 ]] && ruff format --check "${PY_STAGED[@]}" || true

step "ruff check (staged)"
[[ ${#PY_STAGED[@]} -gt 0 ]] && ruff check "${PY_STAGED[@]}"

step "mypy --strict (staged)"
[[ ${#PY_STAGED[@]} -gt 0 ]] && mypy --strict --no-incremental "${PY_STAGED[@]}"

step "bandit (staged eyenet/*)"
EYENET_PY=()
for f in "${PY_STAGED[@]:-}"; do [[ "$f" == eyenet/* ]] && EYENET_PY+=("$f"); done
[[ ${#EYENET_PY[@]} -gt 0 ]] && bandit -c pyproject.toml --quiet "${EYENET_PY[@]}"

step "detect-secrets (CRITICAL — identity-pool blobs / age keys must not slip in)"
detect-secrets-hook --baseline .secrets.baseline "${STAGED[@]:-}"

step "deptry"
deptry eyenet

step "pytest unit+contract with coverage gate (≥95% + no delta drop)"
pytest -m "unit or contract" -q --cov=eyenet --cov-report=json:coverage.json \
       --cov-fail-under=95
. "$(dirname "$0")/lib/coverage.sh"
coverage_no_drop coverage.json .coverage-baseline

step "pre-commit OK"
```

### 5.3 `.githooks/pre-push`

```bash
#!/usr/bin/env bash
set -euo pipefail
. "$(dirname "$0")/lib/common.sh"

step "ruff check (full)"
ruff check eyenet tests contracts

step "mypy --strict (full)"
mypy --strict eyenet contracts

step "pytest unit + integration + contract (full coverage gate)"
pytest -m "unit or integration or contract" -q \
       --cov=eyenet --cov-report=json:coverage.json \
       --cov-fail-under=95
. "$(dirname "$0")/lib/coverage.sh"
coverage_no_drop coverage.json .coverage-baseline

step "pip-audit --strict"
pip-audit --strict

step "pre-push OK"
```

### 5.4 `.githooks/lib/coverage.sh`

```bash
# coverage_no_drop <coverage.json> <baseline.json>
# Refuses if the new line_rate is below the baseline by more than 0.0001 (rounding tolerance).
coverage_no_drop() {
  local cov="$1" base="$2"
  local new
  new=$(python -c "import json,sys;print(json.load(open(sys.argv[1]))['totals']['percent_covered']/100)" "$cov")
  if [[ ! -f "$base" ]]; then
    echo "{\"line_rate\": $new}" > "$base"
    git add "$base"
    return 0
  fi
  local old
  old=$(python -c "import json,sys;print(json.load(open(sys.argv[1]))['line_rate'])" "$base")
  python - "$new" "$old" <<'PY'
import sys
new, old = float(sys.argv[1]), float(sys.argv[2])
if new + 1e-4 < old:
    print(f"COVERAGE DROP: {old:.4f} -> {new:.4f} — refusing.")
    sys.exit(1)
PY
  # Update baseline forward (only when delta gate passes)
  python -c "import json,sys;json.dump({'line_rate': float(sys.argv[1])}, open(sys.argv[2],'w'))" "$new" "$base"
  git add "$base"
}
```

### 5.5 Notes

- Hooks fail closed. Any non-zero exit → commit/push refused.
- `git commit --no-verify` is the local-only escape hatch; the pre-push hook re-runs the gate, and Gitea Actions runs it AGAIN. So `--no-verify` only buys you a noisy WIP commit.
- `.coverage-baseline` is committed JSON — every commit that raises coverage advances the baseline; every commit that lowers it is refused. The number ratchets up monotonically.
- `.secrets.baseline` is committed too. Regenerate carefully when fixtures legitimately add token-shaped strings.

---

## 6. Gitea Actions — `.gitea/workflows/`

Gitea Actions YAML is GitHub-Actions-compatible (Gitea ships `act_runner`). Workflows live in `.gitea/workflows/`.

### 6.1 `.gitea/workflows/pr.yml`

```yaml
name: PR
on:
  pull_request:
  push:
    branches: [main, develop]

jobs:
  static:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -e ".[dev]"
      - run: ruff format --check .
      - run: ruff check .
      - run: mypy --strict eyenet contracts
      - run: bandit -c pyproject.toml -r eyenet
      - run: deptry eyenet
      - run: pip-audit --strict

  test-fast:
    runs-on: ubuntu-latest
    needs: static
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -e ".[dev]"
      - run: pytest -m "unit or integration or contract" --cov=eyenet --cov-report=xml --cov-fail-under=95
      - uses: actions/upload-artifact@v3
        with: { name: coverage-xml, path: coverage.xml }

  test-e2e:
    runs-on: ubuntu-latest
    needs: test-fast
    services:
      nats:
        image: nats:2-alpine
        ports: ["4222:4222", "8222:8222"]
        options: --name nats-test
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -e ".[dev]"
      - run: pytest -m e2e -q
        env:
          EYENET_NATS_URL: "nats://localhost:4222"

  benchmark:
    runs-on: ubuntu-latest
    needs: test-fast
    continue-on-error: true   # warn-only until baseline exists
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -e ".[dev]"
      - run: pytest -m benchmark --benchmark-only --benchmark-json=bench.json
      - uses: actions/upload-artifact@v3
        with: { name: bench-json, path: bench.json }
```

### 6.2 `.gitea/workflows/nightly.yml`

```yaml
name: Nightly
on:
  schedule:
    - cron: "0 3 * * *"
  workflow_dispatch:

jobs:
  full:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -e ".[dev]"
      - run: pytest -m "" -q --cov=eyenet --cov-fail-under=95
      - run: bandit -r eyenet -f json -o bandit.json
      - run: pip-audit --strict --format json --output pip-audit.json
      - uses: actions/upload-artifact@v3
        with:
          name: nightly-reports
          path: |
            bandit.json
            pip-audit.json

  calibration:
    runs-on: ubuntu-latest
    if: ${{ secrets.RUTIFY_CORPUS_KEY != '' }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -e ".[dev]"
      # Decrypt the labeled corpus from age-encrypted artifact in repo or LFS.
      - run: ./scripts/fetch-corpus.sh
        env:
          RUTIFY_CORPUS_KEY: ${{ secrets.RUTIFY_CORPUS_KEY }}
      - run: pytest -m calibration --no-cov
```

### 6.3 Gitea-specific notes

- `actions/checkout@v4`, `actions/setup-python@v5`, `actions/upload-artifact@v3` all run under `act_runner` exactly like GitHub Actions. Gitea proxies them via its actions registry.
- Self-hosted runner is the right call for EYENET — labeled-corpus material and identity fixtures should not leave operator-controlled infrastructure. Set runner labels accordingly (`runs-on: self-hosted`).
- `${{ secrets.* }}` works the same as GitHub. Store `RUTIFY_CORPUS_KEY` (age key) and any operator tokens in Gitea repo secrets.
- The local hooks (§5) and Gitea Actions deliberately overlap — hooks are the developer's gate, Actions are the team's backstop. Either alone is insufficient.

---

## 7. Test layout

```
tests/
├── unit/                  # @pytest.mark.unit
│   ├── contracts/         # @pytest.mark.contract  (CDD gate)
│   ├── sensor/
│   │   └── primitives/    # @pytest.mark.primitive — one file per primitive
│   ├── engine/
│   ├── linker/
│   └── ...
├── integration/           # @pytest.mark.integration
│   └── (in-memory bus, multi-service)
├── e2e/                   # @pytest.mark.e2e
│   └── (testcontainers NATS, full pipeline)
├── calibration/           # @pytest.mark.calibration
│   └── (Rutify corpus, AUC, discrimination)
├── benchmark/             # @pytest.mark.benchmark
├── schema/                # @pytest.mark.schema (deferred until API exists)
├── load/                  # locust files; NOT pytest
└── fixtures/
    ├── corpora/
    ├── factories/         # polyfactory factories per Pydantic model
    └── snapshots/         # syrupy snapshots
```

---

## 8. Fixture / factory rules

- **One polyfactory factory per Pydantic model.** Test code constructs valid instances by `ActorFactory.build()`, never hand-built dicts. When the model changes, the factory follows; tests don't drift.
- **Snapshot tests via syrupy** for graph-state and profile-shape assertions. Snapshots reviewed manually on update — never `--snapshot-update` in CI without a human in the loop.
- **`freezegun` for any test that touches `temporal_evolution.*` primitives or `*_at_*` timestamps.** Real-clock tests in calibration only.
- **`respx` for forum/RSS collectors.** No real HTTP at unit/integration tier.

---

## 9. What we explicitly DO NOT test

- The third-party libraries we depend on (Telethon, sqlite-vec, NATS client). We test our adapter layer against them, not them.
- Production telemetry collectors / OTLP backends. Tracing instrumentation correctness is verified via in-process span capture, not by spinning up Tempo.
- Operator UX flows that don't exist yet (no UI in v0).

---

## 10. Open questions

1. **CI backend:** GitHub Actions vs GitLab vs self-hosted. Doesn't change this doc; affects only the CI YAML.
2. **Mutation testing trigger:** weekly vs per-release. Lean per-release.
3. **Coverage delta enforcement:** block PR on >2% drop, or just report? Lean report-only until we have history to baseline against.
4. **Benchmark regression threshold:** lock in once we have baseline numbers (Milestone 2).
