# Indicator extraction, dedup + provenance, DB ruleset (design)

Decisions locked (ANTI, 2026-10-14): DB-only ruleset (vendored rows seeded by
migration, `enabled` = operator state); dedicated `indicator` + `indicator_mention`
tables; Postgres-primary (no SQLite-specific work, `pg_trgm` not FTS5).

## Schema (SQLModel metadata + ONE Postgres incremental migration)

```
indicator_rule
  id            UUID pk
  kind          str        # "handle","wallet_btc", ... (the token namespace)
  pattern       str        # python re source
  fold_case     bool       # normalize value to lower() or preserve
  enabled       bool       # OPERATOR STATE. vendored upgrades NEVER touch this.
  vendored      bool       # True = shipped default; False = operator custom
  description   str
  created_at / updated_at
  UNIQUE(kind, pattern)

indicator
  id            UUID pk (uuid7)
  kind          str  index
  value_raw     str        # first-seen surface form (evidence)
  value_norm    str        # dedup key
  first_seen / last_seen  datetime
  UNIQUE(kind, value_norm)          # <-- dedup happens here

indicator_mention                   # the provenance edge ANTI wants
  id            UUID pk (uuid7)
  indicator_id  UUID fk -> indicator.id  index
  message_id    UUID fk -> message.id    index   # actor+source+thread reachable via message
  char_offset   int | None
  ts            datetime
  UNIQUE(indicator_id, message_id)  # one edge per (indicator, message)
```

Why message_id and not a wide edge: `message` already carries `source_id`,
`actor_id`, `group_id`, `sent_at_source`, `template_id` (MessageTable). Join
through it; don't denormalize what's one FK away.

`df_actors` (the infra_linker ambient-handle guard) = `COUNT(DISTINCT message.actor_id)`
over mentions, computed on read. Denormalize to a counter ONLY if measured slow.
(ponytail: query first, counter when the linker hot loop proves it needs one.)

Postgres migration (new rev on `postgres_repo` tree, down_revision = 0006):
create the 3 tables, `UNIQUE` indexes, `INSERT ... ON CONFLICT DO NOTHING` the
vendored rule catalog. SQLite: tables come free from the create_all baseline;
no incremental (per project_sqlite_deprioritized + column-migration memory).

## Extractor refactor (`eyenet/linker/indicators.py`)

`extract_indicators(text)` stays a pure function but is driven by a compiled
ruleset instead of module-level regexes. Ruleset compiled ONCE per process from
enabled rows; API mutation bumps a reload. Keeps infra_linker's existing
`"<kind>:<value>"` token contract, so `propose_infra_edges` is untouched.

New persistence seam (flat method on BaseRepository, mixin impl):
`record_indicators(message_id)` -> extract from that message body, upsert
indicator nodes (ON CONFLICT bump last_seen) + mention edges. Called from the
ingest/sensor path after a message lands. Batch variant for backfill.

## Default rule catalog (REVIEW THESE)

| kind | pattern (python re) | fold | notes |
|---|---|---|---|
| handle | `(?<![\w.%+-])@([A-Za-z0-9_]{4,32})` | lower | FIX: lookbehind stops email domains being read as handles |
| tme | `t\.me/(\+?[A-Za-z0-9_/]{3,64})` | lower | unchanged |
| wallet_evm | `\b0x[a-fA-F0-9]{40}\b` | lower | ETH/EVM, unchanged |
| wallet_trx | `\bT[1-9A-HJ-NP-Za-km-z]{33}\b` | NO | TRON base58, unchanged |
| wallet_btc_b58 | `\b[13][1-9A-HJ-NP-Za-km-z]{25,34}\b` | NO | legacy P2PKH/P2SH, base58 case-sensitive |
| wallet_btc_bech32 | `\bbc1[a-z0-9]{25,62}\b` | lower | segwit |
| wallet_xmr | `\b[48][0-9AB][1-9A-HJ-NP-Za-km-z]{93}\b` | NO | Monero 95-char standard addr |
| email | `\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b` | lower | also covers XMPP/Jabber syntactically |
| session | `\b05[0-9a-f]{64}\b` | lower | Session ID = 05 + 64 hex |
| tox | `\b[0-9A-Fa-f]{76}\b` | lower | Tox ID = 76 hex (distinct length vs sha256=64) |

## Three judgment calls (ANTI rules on these)

1. **hashes (md5/sha1/sha256)** — proposed DEFER / context-gated only. Any hex
   run matches; huge false-positive surface, collides with tox/session/pgp. And
   a file hash IDs *malware*, not an *operator* -> weak linkage signal. Ship only
   a context-gated rule (`(?:md5|sha1|sha256|hash)[:= ]\s*<hex>`) or skip v1.

2. **PGP** — fingerprints are 40-hex (collides with SHA-1) and usually shown as
   a key block or `0x`-prefixed long key id. Proposed: extract the key BLOCK
   (`-----BEGIN PGP ...`) and `0x[0-9A-Fa-f]{16,40}` key ids only; skip bare
   40-hex to avoid the hash collision. Low volume, high value when present.

3. **Jabber/XMPP vs email** — syntactically identical. Proposed: one `email`
   kind now; add an operator-tunable `jabber` re-tag rule keyed on known XMPP
   domains later (this is exactly what the DB ruleset is FOR).

## Security / correctness

- Operator-custom regex = ReDoS risk (`re` has no timeout). Guard: test-compile
  + cap pattern length at API write; cap input text length at extraction.
- onion is ALREADY extracted (`sensor/discovery/url_extraction.py:39`). Do NOT
  re-regex; unify at the persistence layer so onions land as indicators too.
- base58 kinds (trx/xmr/btc_b58) are case-sensitive: never fold.

## Build order (incremental commits to main)

1. Schema: models + PG migration + vendored seed. (foundation)
2. Extractor driven by ruleset + expanded catalog + the handle lookbehind fix.
3. `record_indicators` persistence + ingest hook + backfill.
4. API: `GET /indicators` (filter by kind/value, mentions), rules CRUD
   (`GET/PATCH/POST /indicators/rules`) Wazuh-style enable/disable.
