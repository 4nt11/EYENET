# gotractor

Go implementation of the EYENET stealer DSL rule engine. Replaces the
original hardcoded `ulpextract.go` monolith with a fully catalog-driven
extractor that shares one spec with the Python (`eyenet/stealer/rules/`)
and browser-side (`eyenet-fe/src/lib/stealer-engine/`) engines.

**Three engines, one spec, enforced by one golden-fixture suite.**

## Build

```
cd eyenet/stealer/gotractor
go build -o gotractor .
```

## Run

```
export EYENET_STEALER_RULES_DIR=/etc/eyenet/rules/stealer
export EYENET_STEALER_FAMILIES_DIR=/etc/eyenet/families/stealer

./gotractor --mode=records --input /path/to/victim/folder
```

### Output modes

| flag              | emits                                                    |
|-------------------|----------------------------------------------------------|
| `--mode=records`  | one JSON line per EXTRACTED RECORD (pipeline default)    |
| `--mode=summary`  | single JSON RunResult (family + merged fields + evals)   |
| `--mode=selftest` | exits 0 after loading the catalog                        |

### Records-mode line shapes

A header line declares the container verdict:
```
{"kind":"verdict","family":"redline","root":"6627[BR]...","files":136}
```

Each extracted record:
```
{"kind":"record","rule_id":"netscape_cookies","family":"cookies",
 "file_path":"Browsers/Cookies/Chrome_Profile_1.txt",
 "fields":{"cookie_domain":".example.com","cookie_name":"sid",...}}
```

Per-(rule, file) truncation notice when a bulk run exceeded the limit:
```
{"kind":"truncated","rule_id":"netscape_cookies","file_path":"...",
 "emitted":100000,"total_seen":128443}
```

## Parity tests

```
go test ./engine/
```

Runs the shared `tests/fixtures/stealer_rules/` suite through the Go
engine and compares every fixture's extracted fields against the
expected.json. A divergence vs the Python or JS engine on ANY fixture
fails the build.

Override the fixtures dir via `EYENET_STEALER_FIXTURES_DIR` when running
from somewhere other than the module root.

## Matcher + verb coverage

- 8 match types: `folder`, `regex`, `delimiter`, `template`, `json`,
  `yaml`, `keyvalue`, `keyvalue_ini`
- 7 normalize verbs: `strip_whitespace`, `lowercase`, `uppercase`,
  `truncate`, `int_from_string`, `replace_re2`, `date_parse`
- `reject_patterns` (RE2 regex list, rejects whole record if any hits)
- `requires_container_family` (content-rule opt-in family gate)
- Null-byte escape (raw `\x00` → literal `\x00` for forensic visibility)
- JSONPath-lite order-preserving extraction
- YAML 1.2 Core schema (Norway-safe: `Country: NO` stays the string "NO")

## Not yet wired (follow-ups)

- Hot-reload via fsnotify on `--rules-dir` changes (SIGHUP equivalent)
- Prometheus metrics endpoint (per-rule record/sec, latency histograms)
- Pipeline-side swap: Python pipeline currently still calls
  `ulpextract.go` via subprocess. Next commit adds a `gotractor_path()`
  helper mirroring `ulpextract_path()` and switches the call site.
- ClickHouse schema migration: new `stealer.extracted_records` table
  with `Map(String, String) fields`; keeps the ulpextract 8-column
  table during the cutover.
