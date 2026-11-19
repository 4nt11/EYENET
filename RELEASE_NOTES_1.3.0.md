# EYENET 1.3.0 - ULP, remade from the ground up

**Headline:** the entire stealer-logs stack has been rebuilt. The old
`ulpextract` Go binary is dead; `gotractor` owns the whole credentials
surface, driven by an operator-editable rule catalog with hot reload, a
MITRE ATT&CK-tagged family taxonomy, and a performance profile that is
roughly **10x faster**, **3x broader coverage**, and uses **~400 MB of
RAM under sustained load** instead of climbing until it dies.

Better, faster, more stable, cheaper, and meaner.

---

## What changed, at a glance

- **Coverage:** 148k credentials from the sample corpus (vs 57k on 1.2.x);
  3.07M records across every family (passwords, cookies, autofills,
  tokens, history, bookmarks, clipboard, wallets, process lists, system
  profile, more).
- **Throughput:** sustained 125-135 archives/s on a 12-core box with a
  12-thread gotractor daemon, pegged at 100% CPU during a batch, dropping
  to idle between batches. Pass 100 of a 100-pass soak was 43% faster
  than pass 1 (warmup only). Zero drift over 306 million records.
- **Memory:** 400-640 MB RSS steady state, actively returned to the OS,
  no goroutine leak, no steady growth. Prior iterations were climbing
  past 22 GB.
- **Operator workflow:** rules and families are now editable through the
  HTTP API and the Rule Builder UI, flowing through a shared catalog
  volume so changes hit the gotractor daemon in <250 ms via fsnotify
  hot-reload. No rebuild, no roll, no restart.
- **Attribution:** Khazan correctly re-classified as an aggregator, not
  a stealer. The logs under the Khazan brand are Vidar output (packed by
  AWARE Crypter) that Khazan's operators repackage and resell. One
  stealer, one packer, one distributor.

---

## Stealer pipeline: ulpextract is dead

The old 9-column `stealer.creds` table was fed by a Go `ulpextract` binary
that only parsed `passwords_block_*` files, lost everything else, and
contributed ~3.5 min of the per-archive wall time. It is tombstoned:

- The `ulpextract` Go source is deleted.
- The `Dockerfile.stealer` build stage that produced it is gone.
- `ClickHouseCredsSink`, the `_COLUMNS`/`_CREATE_TABLE` constants, and
  the `creds_inserted` field on `ProcessResult` are removed.
- `StealerCredsReader` now reads `extracted_records` with a family
  allowlist (browser_passwords, windows_credentials, firefox_logins,
  combolist) and canonicalises host/scheme/tld at READ time with
  ClickHouse URL functions (`domain()`, `protocol()`, `topLevelDomain()`),
  so rows captured as raw URLs still produce clean host output without a
  reindex.
- The legacy `stealer.creds` table is NOT auto-dropped; operator decides
  when it is safe to go. The PG `creds_extracted` column is kept and now
  stores the gotractor emit count.

Under the hood: gotractor's DSL parsed 148,096 real credentials from the
same corpus the old pipeline got 57,000 from, with 24,000 distinct hosts.
2.6x lift, strict upgrade, no regressions.

---

## Rule DSL + hot reload

`eyenet/stealer/rules/catalog/` ships with 74 vendored rules spanning 44
families. The rule language is a declarative YAML DSL with matcher types
(`regex`, `delimiter`, `template`, `json`, `yaml`, `vdf`, `xml`,
`keyvalue`, `keyvalue_ini`), a predicate tree for compound matches
(`and`/`or`/`not`/`min_score`), a normalize pipeline (`derive_url_parts`
via publicsuffix, `date_parse`, etc.), reject patterns, and MITRE
ATT&CK TTP tags on every rule.

Changes land live:

- **HTTP API**: `/v1/stealer/rules` + `/v1/stealer/families` CRUD. Writes
  atomic (validate -> temp -> fsync -> rename), slug on an allowlist regex.
- **Shared volume**: both the API container and the stealer-processor
  mount `/var/lib/eyenet/stealer-catalog/`. Writes from the API flow
  straight to the gotractor daemon's watched directory.
- **fsnotify + debounce (250 ms)**: a batch of saves triggers one reload.
  No rebuild, no roll, no restart.

The vendored catalog seeds the shared volume lazily on first boot and
never overwrites operator edits, so package upgrades cannot stomp on live
tunings.

---

## Rule Builder UI + Workbench

Two new screens:

**Rule Builder (`/stealer/rules`)** - point-and-click editor over the
three-layer catalog (container -> content, with derived L2 highlighted
inline). Predicate tree quickpicker for compound matches. Live JSON side
panel mirrors the YAML on disk as you edit. Families CRUD in the sibling
`/stealer/families` screen.

**Rules Workbench (`/stealer/workbench`)** - client-side rule evaluation
on a folder the operator picks locally. Shows per-file rule hits,
predicate-tree evaluations, rule-trace timing, and record previews. Uses
`re2js` under the hood (pure-JS, Vite-friendly) so there is no WASM
hosting dependency.

Both screens use the same rule engine the backend uses, compiled for
the browser. What you see in the workbench is what the gotractor daemon
will emit on the real corpus.

---

## Family classifier + operator overrides

Per-victim family verdicts now ship with:

- Per-family P/R metrics on the classifier dashboard.
- Dry-run tester (operator pastes a rule change, sees expected classification
  deltas before saving).
- Operator overrides (`stealer_family_override` table, migration 0024)
  with reclassify UI.
- Reclassify + reindex endpoints (single archive + whole corpus), bus-
  dispatched so the worker fleet shares the load.

Audit chain is tamper-evident on every classifier action, same posture as
the rest of the stealer surface (`read:stealer` clearance is expiring,
`write:stealer` / `admin:stealer` for edits).

---

## Wallet extraction + LevelDB vaults

Browser-wallet LevelDB vaults (MetaMask, Phantom, Rabby, etc.) are now
extracted by gotractor directly. Required a custom LevelDB comparer
(`idb_cmp1`) because IndexedDB uses its own key-ordering that the stock
`syndtr/goleveldb` could not open. Shipped behind the vendored binary.

Exodus desktop wallet JSON metadata (passphrase + config) parsed as a
sibling family. Tier-1 binary DSL support added via ASCII-safe regex for
the handful of patterns that need raw-byte matching inside otherwise-text
files.

---

## New rules shipped

Per-file families landed this cycle (not exhaustive):

- `Clipboard.txt` per-line snapshots
- `LocalStorage.txt` baseline + JWT candidates
- `Environment.txt` Windows env-var extraction
- `UserInformation.txt` four-shape coverage
- `Summary.txt` browser profile list
- `Information.txt v29` (Khazan)
- `Gabb` file-grabber sidecar (json_v2 companion)
- `netscape_cookies` + `cookies_netscape_tsv` (cookies meta-family)
- `AWARE Crypter` calling-card detection
- Full `[Hardware]` INI section extraction for Khazan v2.9

---

## Attribution finding: Khazan is an aggregator, not a stealer

What we were tracking as a distinct "Khazan" stealer family turns out to
be Vidar output (packed by AWARE Crypter) repackaged and resold under
the Khazan brand. Khazan itself is the distributor layer, not the
exfiltration layer. The AWARE Crypter calling card is extractable and
the Information.txt v29 schema now captures the packer metadata
explicitly, so stealer-level attribution (Vidar) and distribution-level
attribution (Khazan) are tracked on separate axes instead of collapsed
into one label.

---

## gotractor engine rewrite

The per-archive processing path is a different animal:

- **Parallel dispatch**: the daemon was processing commands serially on a
  single goroutine. Replaced with a `runtime.NumCPU()`-bounded worker
  pool. `reload`/`stats`/`shutdown` stay serial and drain in-flight runs
  first. Overridable with `EYENET_GOTRACTOR_WORKERS`.
- **Streaming writer**: the per-emit mutex is gone. Workers marshal
  records to a pooled `bytes.Buffer` in parallel, send it through a
  channel to a dedicated writer goroutine that owns a 128 KB
  `bufio.Writer`. All the reflection cost of encoding/json scales across
  workers now instead of blocking a single writer lock. Oversized buffers
  (>8 KB cap) are dropped rather than returned to the pool.
- **Regex compile cache**: `MatchRegex` and `MatchGlob` were each
  recompiling their regex on every call. At per-line bulk-parse rates
  this was 43% of total allocation. Two `sync.Map` caches, one compile
  per unique pattern forever.
- **pre_contains prefilter**: twelve `**/*.txt` regex rules used to run
  a full RE2 pass over multi-MB cookies files and never match. A cheap
  rule-declared substring check (plus Go's `LiteralPrefix` fallback)
  short-circuits before touching the regex engine.
- **Zero-alloc line iterator**: `strings.Split` built a full `[]string`
  sized to the file. Replaced with an `iter.Seq` that slices directly
  via `strings.IndexByte`. `strings.genSplit` dropped out of the top
  allocation sites.
- **iter.Seq for all matchers**: the channel-based generator idiom
  (`Iter{Delimiter,JSON,VDF,XML}`) leaked a goroutine per call when the
  sibling `Match*` function took one row and returned. At production
  throughput this compounded to ~150 k live goroutines in minutes, each
  pinning 8 KB of stack + a record reference + a slice into the whole
  file text. Converted all four to synchronous `iter.Seq` callbacks.
  Zero goroutines leaked, zero channel contention, safe early-exit.
- **pprof HTTP endpoint**: `/debug/pprof/*` registered on the same mux
  as `/metrics` so the daemon can be scraped live in prod when things
  look off.

Soak: 787 extracted victim folders, 100 passes, 78,700 archives,
**306,944,087 records** processed through one long-lived daemon. Zero
drift, pass 100 was faster than pass 1, RSS stable at 400-640 MB.

Full writeup in `development/poc-gotractor/PERF_NOTES.md`.

---

## Migrations

**One migration** in this release:

- `0024_stealer_family_override` - operator family-verdict override
  table + `override_at` / `override_reason` columns.

Postgres only, expand-only, additive, honours the
`upgrade_to_head`-auto-migrates-on-boot invariant. The release is safe
to deploy without a maintenance window on this axis.

ClickHouse schema change: `victim_profiles.{safecount}` widened from
UInt32 to UInt64 (fix for a pre-existing overflow risk on big corpora).

---

## Operator-visible fixes

- `creds_extracted` column no longer tied to a Go binary that no longer
  exists. Now reflects gotractor emit count.
- Drawer routing fixed (pre-1.3 the drawer could crash on concurrent
  opens; `StealerArtifactsReader`, `StealerCredsReader`, and
  `FileAuditReader` are all async-safe now).
- `monitored_domains` JOIN rewrite so the artifact drawer does not dupe
  rows.
- Delimiter rules now honour integer YAML keys (yaml.v3 quirk).
- `pyyaml` moved from optional to runtime deps - the stealer surface
  needs it unconditionally.

---

## FE: stealer screens

- Artifact drawer on `/stealer/artifacts` (v1.3.3 + v1.3.4 precursor
  work)
- Rule Builder UI (families, rules, three-layer view)
- Rules Workbench (client-side evaluator, folder picker, rule trace)
- Classifier dashboard with per-family P/R metrics
- Family detail pages with per-family victim counts
- Drawer verdict tile + family filter on the list view

Served from `bun run dev` locally; no Caddy rebuild for FE changes.

---

## Deploy notes

- **Migrations:** one new additive migration (0024). `upgrade_to_head`
  runs on boot; no manual step required.
- **Shared catalog volume:** `eyenet-data` mounts at
  `/var/lib/eyenet/stealer-catalog/` in both the API and stealer-processor
  containers. First boot after upgrade will lazy-seed the vendored
  catalog into the empty volume; subsequent boots keep whatever the
  operator has edited.
- **ulpextract removal:** the `stealer.creds` ClickHouse table is NOT
  auto-dropped. Operator runs the drop manually when historical queries
  are known to be clear.
- **Reprocess:** the `stealer-reindex` CLI + `/v1/stealer/reindex`
  endpoints can walk the existing corpus and re-emit records under the
  new catalog. For a 2 M-row corpus this is minutes, not hours, with the
  new daemon.
- **Reset the catalog volume** if you want to adopt fresh vendored
  rules: `docker compose exec stealer-processor rm -rf
  /var/lib/eyenet/stealer-catalog/rules /var/lib/eyenet/stealer-catalog/families`
  then roll the processor - lazy seed replays vendored defaults.
- **Prometheus:** the daemon metrics endpoint stays on port 9091.
  pprof is on the same port, path prefix `/debug/pprof/`.

---

## Known issues / shipping with it anyway

Things we know are broken or half-built. Documented here so support
tickets don't have to re-discover them. Fixes land in 1.3.x minor
releases as they get prioritised.

### Slow endpoints (will fix in 1.3.x)

- `/v1/stealer/artifacts/{sha}/archive` + `/v1/stealer/artifacts/{sha}/archive/files`
  are TERRIBLY slow. We know. We will fix it.
- `/v1/stealer/stats` is also TERRIBLY slow, 0.2-3s per load.
- The general artifacts page is still slow as fuck.
- The general search function is still slow as fuck.
- Parse-failures section in the stealer configurations page is also
  terribly slow, up to 4s to load.

### Stealer UI / data gaps

- The ULP corpus page still shows only creds / hosts / unique h:l:p. No
  metadata info, no cookie count. Terrible.
- The cookie subsection in the artifact drawer page looks terrible.
- The cookie subsection is also MISCOUNTING - profiles with 0 real
  cookies render as "12,102 rows, page 1/243". Known bug.
- Indicator extraction is mangled: `#httponly_.roblox.com` is the only
  indicator extracted out of a million cookies per profile.
- The family dropdown on the artifacts page uses the default browser
  dropdown instead of our combobox. Will swap.

### Half-built / deferred features

- Global post-processing pipeline config is still a stub and will
  probably be removed - we moved to per-rule normalization pipelines
  and the global one serves no purpose anymore.
- Live feed is still dead, not a priority. Not now, not tomorrow.
  Endpoints are built, haven't done it yet.
- Candidate triage page is still terrible, loads everything at once.
  Use the monitored-groups page, sorry.
- Linkages still SUCK and the page is still ugly. Needs a redesign.
  Not a priority.
- Cases are still mostly stubs. Known. Not a priority. "But anti, this
  is a CTI tool!" - yeah fuck you, build it yourself.
- Document classifier is still dead.

---

## Credits

Thanks to the external sessions and second-opinion audit passes that
turned research leads into mental models and caught the 150k-goroutine
leak before it shipped. The PoC prototyping environment
(`development/poc-gotractor/`) earned its keep twice over this cycle.
