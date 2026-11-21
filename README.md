<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

> # :rotating_light: HEY MORON, THIS PROJECT IS IN EXPERIMENTAL PHASE. :rotating_light:
> # USE AT YOUR OWN RISK! :3
>
> Schema changes land weekly. Migrations exist but are not bulletproof.
> Prod-shaped bugs will land in your lap. If you are reading this and
> thinking "neat, let me run it on real data," think again, then do
> whatever you want anyway, you beautiful cowboy.

---

# EYENET

Observation framework for **forensic analysis of threat actors**. EYENET
consumes [BEHAVE-TEXT](../BEHAVE/BEHAVE-TEXT) behavioral primitives and is a
sibling of DECNET. Built for **small operators** (the analyst running a few
collectors, not an enterprise SOC) with an **operator-grade evidence** posture:
retain full content, audit every access, never hobble the operator.

## What EYENET is (and is not)

**It is** a self-hosted observation and correlation stack for messaging and
forum activity. You wire up collectors (Telegram, Matrix, forum boards), the
pipeline normalizes everything into messages with identities, attachments, and
derived behavioral primitives, then surfaces actors, crews, linkages, infostealer
victims, and incidents through a SvelteKit UI and a versioned HTTP API.

**It is not** an enterprise SIEM, a SOAR, a honeypot, or a malware sandbox. It
does not try to be real-time. It does try to hold full evidence that a court
or a sober adult would accept: hash-chained audit log, signed file-access
journal for sensitive evidence, every access logged with a reason.

## What is shipped

### Collectors

- **Telegram** (user-mode via Telethon), multi-account with identity rotation
  and health, invisible mode, backfill on attach, attachment capture past
  Telegram's category cap.
- **Matrix** (nio), always-invisible (`set_presence=offline` is hard-coded, no
  operator knob), multi-account.
- **Forum collector** for MyBB-shaped boards, bypasses measured live against
  real walls:
  - **Clearnet, DDoS-Guard + Cloudflare**: TLS is impersonated as real
    Firefox via `curl-cffi` (target `firefox147`, mirroring the Firefox 152
    browser that minted the cookie jar), not httpx, because httpx's OpenSSL
    ClientHello is an unmistakable "Python" tell (35 ciphers, HTTP/1.1).
    For strict Cloudflare JA4 walls the collector forces exact cipher +
    signature-algorithm lists via `extra_fp`, captured with
    `development/poc-browser/capture_ja3.py`.
  - **Tor onion path**: stays on httpx. Tor wraps the TLS so JA3
    impersonation is moot through the onion.
  - **Warmed cookie jars**: UA, JA3/JA4, and cookie-mint browser must all
    be the same Firefox; a mismatch is a stronger ban signal than no
    impersonation at all. Jars + accounts are rotated, and spares are kept
    warm because DDoS-Guard bans the *account*, not the IP.
  - **Evasion presets**: `smash` / T4 (0.5 to 1.5 seconds between requests)
    rides clean against measured targets; sustained near-max is
    deliberately *not* used until bursty human-hours windowing lands,
    because the wall is per-account rate logic, not the volumetric gate.
  - **Header + decoder coherence**: `Accept-Encoding` is omitted on
    purpose so each client advertises only the codecs it can actually
    inflate (gzip/deflate/br/zstd on httpx, curl-cffi sets its own).
  - **Relative-date parsing** (`Today, HH:MM`, `N hours ago`) is treated
    as load-bearing: substituting `now()` for a missing timestamp would
    manufacture false recency and misstamp an old leak as fresh, so the
    parser raises hard instead of guessing.
- **Discovery/anchor** services that push candidates into the monitor queue
  and resolve mentions. The payoff is **artifact-to-group resolution**: a
  Telegram group mentioned inside a forum post surfaces as both an
  artifact (queryable with every other indicator) *and* a first-class group
  you can start monitoring in one click. The forum mention becomes the
  collector target, instead of the analyst manually hunting the handle.

### Pipelines

- **Stealer / ULP corpus pipeline**. Telegram cap-bypass capture, decrypt
  ladder for archives, gotractor Go engine (DSL-driven rule extraction, chunked
  streaming file ingest, 100+ MiB archives at ~160 MiB RSS), ClickHouse
  landing with ReplacingMergeTree dedup on identity tuple. Rollup
  aggregates use `uniqHLL12` HLL sketches with fixed state size (see the
  v1.3.12.1 release notes if you like a good schema story).
- **Document pipeline** (M10, in progress). Classifier assigns a sensitivity
  tier at reception; parsing happens inside an **nsjail** cage whose
  containment is re-proven on every boot. Fail-closed by default.
- **Incident classifier**. 16-label model on Hugging Face (`4nt11/eyenet-incident`)
  flags posts for the ransomware / stealer / combolist / infra-sale queues.
- **Linker + verifier**. Actors across collectors get merged into personas;
  the verifier runs stylometric and identity checks on the candidates.
- **Graph explorer**. Operator-driven expansion of entities (actors,
  documents, artifacts, cases) through a shared graph index with saved graphs
  and notes.

### Frontend (SvelteKit at `eyenet-fe/`)

The operator UI covers the current set of pages:

- **Cases / Evidence** (attachments, documents, logs, reclassify flow).
- **Actors / Actor groups / Personas / Candidates** for identity work.
- **Collectors / Sources / Collector settings / Proxies / Identities** for
  wiring and rotating accounts.
- **Stealer** dashboard: credential stat tiles, families, by-domain search,
  and per-victim drawers ("stealer artifacts") that open the full record set
  for one infected host.
- **Artifacts** browser (indicators extracted from messages + documents).
- **Incidents / Linkages** for correlated-event work.
- **Monitored groups**: the list of groups EYENET is currently watching, the
  ones it has seen but is not watching, and the button to start watching one.
- **Graph** explorer: a graph-map with a transform system for fast in-place
  correlation (expand an entity, pivot through saved transforms, keep the
  graph for later).
- **Search**: global, not just documents. One box over actors, threads,
  messages, channels, groups, nicknames, and extracted artifacts.
- **Reader**: the analyst's window into every piece of data EYENET has
  scraped, shown per source and per group / category. You read a forum
  without ever opening the forum, and without burning a personal account on
  it. Every scraped piece lands as-is, byte-for-byte, so the record carries
  maximum forensic weight.
- **Lab** for the analyst's desk work (scratchpad, ad-hoc queries, local
  experiments).
- **Control**: the killswitch. In an emergency the control page stops every
  EYENET service at once. Heavily guarded on purpose.
- **Clearance** tier views. Tier-gated reads at every API surface.
- **Health**: live service and pipeline diagnostics.
- **Tuning**: the operator workbench. Covers the gotractor rule + family
  catalog, parse misses, parse failures, canonicalized shapes, and a local
  rule-authoring workbench so a new extraction rule can be tried against
  real archives before it ships.
- **Auth** with MFA.

### Backend API

- Versioned `v1` HTTP API (see [`development/API_PLAN.md`](development/API_PLAN.md)).
- JWT auth with per-user scopes/grants, MFA (TOTP), lockout, rate limits.
- Clearance tiers gating reads.
- Hash-chained audit log in a separate physical database for tamper-evidence.
- Prometheus metrics on every service; OpenTelemetry traces propagated across
  the bus.

## Running

EYENET ships as a Docker Compose stack. There is no "install on bare metal"
path.

```bash
cp deploy/docker/env.example deploy/docker/.env
# edit .env: EYENET_DOMAIN, EYENET_ACME_EMAIL, CH + Postgres creds, etc.
deploy/docker/deploy.sh deploy
```

`deploy.sh deploy` builds images on the host, tags them with the current
version, brings up the stack with the `stealer` profile, verifies health, and
prunes old versions.

- `deploy.sh rollback [VER]` repoints the live tag at a retained version.
- `deploy.sh versions` lists retained vs. running.

The composition is `compose.yaml` + `compose.prod.lite.yaml` with the `stealer`
profile (core services + ULP extractors; no observability, classifier, or
incidents). Edit `deploy/docker/deploy.sh` if the box should run more.

## Operating

Everything is a subcommand of the `eyenet` CLI inside the `api` or
`stealer-processor` container. The ones you actually touch:

### User + access management

```bash
# create a user
docker exec docker-api-1 eyenet user create alice --email alice@example.com

# scopes (grants)
docker exec docker-api-1 eyenet scopes grant   alice stealer:read
docker exec docker-api-1 eyenet scopes revoke  alice stealer:read
docker exec docker-api-1 eyenet scopes list    alice

# reset things when someone loses their phone
docker exec docker-api-1 eyenet user reset-password alice
docker exec docker-api-1 eyenet user reset-mfa     alice
docker exec docker-api-1 eyenet user unlock-mfa    alice
```

### Stealer corpus

```bash
# fire a full corpus reindex over the bus (processor handles it async)
docker exec docker-stealer-processor-1 eyenet stealer-reindex

# dry run: list what would be reindexed
docker exec docker-stealer-processor-1 eyenet stealer-reindex --dry-run

# reindex ONE attachment urgently
docker exec docker-stealer-processor-1 eyenet stealer-reindex \
    --attachment <uuid> --urgent

# housekeeping sweeps
docker exec docker-stealer-processor-1 eyenet artifact-checksum-sweep
docker exec docker-stealer-processor-1 eyenet stealer-reclassify
```

### Everything else

The CLI also owns identity sync, discovery backfill, document ingest, incident
classifier training and inference, graph service, linker, verifier, panic
sweep, and the per-service daemons (`api`, `supervisor`, `anchor`, `engine`,
`geo`, `search-indexer`, `classifier`, ...). `eyenet --help` enumerates the
full set, which is longer than this README should be.

## Documentation

| Doc | What |
|---|---|
| [`PLAN.md`](PLAN.md) | milestone roadmap |
| [`CLAUDE.md`](CLAUDE.md) | architecture, conventions, traps |
| [`deploy/DEPLOY.md`](deploy/DEPLOY.md) | deployment internals + flags |
| [`development/API_PLAN.md`](development/API_PLAN.md) | HTTP API spec (source of truth for `v1` routes) |
| [`development/MODELS.md`](development/MODELS.md) | table-by-table schema reference |
| [`development/CLASSIFIER_PLAN.md`](development/CLASSIFIER_PLAN.md) | Document Classifier design + build plan |
| [`development/STEALER_PIPELINE.md`](development/STEALER_PIPELINE.md) | Stealer / ULP pipeline design |

## License

AGPL-3.0-or-later.
