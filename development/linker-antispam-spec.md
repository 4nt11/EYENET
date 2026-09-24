# Spec: anti-spam linkage — copypasta detection + shared-infrastructure linker

Status: proposed (2026-09-24). Motivated by live linker results on the first
monitored carding/laundering groups: `char_ngram_simhash_hamming` produced 45
"strong" (score 0.0) same-author proposals that were **all** copypasta spam, and
fused two distinct laundering brands ("WBpay", "LV") into one false clique.

## 1. The problem, from the data

Live sample (monitored groups `@cvv190log`, `@DrNexusec`, ...):

- 8 accounts posted **byte-identical** USDT/UPI ad templates → stylometric simhash
  linked all 8 at hamming 0.0 (identical fingerprint).
- Extracting the **contact handles inside the ad bodies** split those 8 cleanly:
  - `@WBpay_*` crew: `8595058147, 8812762841, 7692927596, 8821947165, 8850096350`
    (bridged by the shared handle `@WBpay_mm1888`)
  - `@LV*` / `@HAO111118` / `@anan6688966` crew: `8715218126, 8811179481, 8813990161`
  - **zero handle overlap between the two crews.**

Two lessons, both calibration-grade (same shelf as
`feedback_ner_density_nondiscriminative` and Spanish-simhash-disabled):

1. **Templated text is not authorship.** Identical n-gram profiles mean "same text
   pasted", not "same author". Stylometry (simhash AND the Verifier's NCD, which
   also sees identical text as identical) cannot disambiguate one-operator vs
   franchise vs meme-copy. It must be **gated off templated content**.
2. **Operational infrastructure is the real linkage feature for this population.**
   Shared contact handles / wallets / `t.me` links co-occurring across accounts is
   high-precision and yields real crews. Extract it and link on it.

## 2. Component A — copypasta / near-duplicate detector

Goal: identify long text reposted many times across accounts, flag it, and gate
authorship linkage (simhash + Verifier) on it.

### Data model
New table `content_template` (main.db):

| col | type | note |
|---|---|---|
| `id` | uuid pk | |
| `fingerprint` | text unique | see normalization below |
| `first_seen_at_ingest` | datetime | |
| `last_seen_at_ingest` | datetime | |
| `occurrence_count` | int | total messages with this fingerprint |
| `distinct_actor_count` | int | distinct posters |
| `char_len` | int | length of the normalized text |
| `sample_body` | text | one representative body (evidence) |

`MessageTable` gains nullable `template_id: uuid | None` (FK). Register both in the
explicit `_MAIN_TABLES` DDL list (see `feedback_ddl_explicit_table_list`).

### Fingerprint (phase 1 — exact-normalized, cheap, catches what we see)
`fingerprint = sha256(normalize(body))` where `normalize` =
- lowercase, NFKC,
- strip emoji + non-letter/digit runs to single spaces,
- collapse whitespace,
- **mask volatile tokens** so "same ad, different amount/handle" still collapses:
  replace digit runs → `#`, `@handles` → `@`, urls → `U`, wallet-shaped tokens → `W`.

Masking is deliberate: the ad copy is the template; the amounts/handles are the
variable slots. Masking makes the template the identity and — bonus — lets the
distinct handles that *vary* per repost fall out as the infra signal (Component B).

### Fingerprint (phase 2 — near-dup, only if phase 1 misses)
MinHash over word-shingles (k=5) + LSH banding, Jaccard ≥ 0.9 → same template.
`datasketch` if a dep is justified; else a 64-bit SimHash-of-shingles with a small
hamming threshold. **Do not build this until phase-1 exact-masked misses real
near-dupes** (YAGNI — the observed spam is verbatim).

### Flagging thresholds (calibrate on the live corpus)
A fingerprint is a **copypasta template** when
`char_len >= 200 AND distinct_actor_count >= 3`. Both tunable in operator TOML.
The observed USDT ads: ~300–1500 chars, 3–8 posters → caught comfortably.

### Effects
- **Gate authorship linkage:** the stylometric sensor and the Verifier skip a
  message whose `template_id` is a flagged copypasta template. Templated text never
  drives a `shared_author` edge again.
- **Surface it:** emit a `ReviewFlag` / actor annotation `posts_copypasta_template`
  and expose template membership on the actor + a `GET /v1/templates` read surface
  (top templates by reach = a spam-campaign leaderboard, genuinely useful).

## 3. Component B — shared-infrastructure co-occurrence linker

Goal: link actors by operational indicators harvested from message content +
Telegram entities. This is the high-value piece.

### Extraction (`eyenet/sensor/indicators/`)
Per ingested message, extract indicators from **both** the body (regex) and the
Telegram **message entities** (`MessageEntityMention` / `MessageEntityTextUrl` give
handles/links without brittle regex — prefer entities, fall back to regex):

| kind | matcher |
|---|---|
| `handle` | `@[A-Za-z0-9_]{4,}` + entity mentions |
| `tme` | `t.me/...` + entity urls |
| `wallet_trx` | `\bT[1-9A-HJ-NP-Za-km-z]{33}\b` |
| `wallet_evm` | `\b0x[a-fA-F0-9]{40}\b` |
| `wallet_btc` | bech32 / base58 (phase 2) |
| `phone` | E.164-ish (guard hard — noisy) |

New table `actor_indicator` (main.db): `(actor_id, kind, value, first_seen,
last_seen, count)`, unique on `(actor_id, kind, value)`. Register in DDL list.

### Linkage
Two actors sharing ≥1 indicator → propose a linkage:
- `method = "shared_infra"`
- `score` = **weighted Jaccard** of indicator sets, where each shared indicator is
  weighted by **rarity (IDF)**: `w(v) = log(N_actors / actors_with(v))`. A handle in
  2 accounts is strong; one in 300 (a group's own @admin) contributes ~0.
- `evidence = {"shared": [values...], "weighted_jaccard": x, "top_indicator": v}`.
- Reuse the existing `linkage` table + `PROPOSED` state machine (no new store shape).

Guard against garbage edges: a **stoplist / max-DF cap** — an indicator appearing in
> `max_df` actors (e.g. the group's pinned admin handle) is excluded from linking.
This is the IDF idea made hard-cut for cheapness.

### Crews
Connected components over `shared_infra` edges (above a weight floor) = **crews**.
`@WBpay_mm1888` bridging the two WBpay sub-groups is exactly the edge that makes the
5-account WBpay crew one component, separate from the 3-account LV crew. This is the
concrete arrival of the "actor groups/crews" concept
(`project_two_group_types_future`) — feed these components into that grouping when it
lands; until then, surface them as a `GET /v1/actors/{id}/related?method=shared_infra`
read + a crew id on the linkage evidence.

## 4. Component C — actor labeling (the "I only see numeric ids" fix)

Not a capture bug: `real.py:811` already stores `@{sender.username}` when present
(148/395 actors have one) and `current_display_name` (first+last) always. The 247
username-less accounts are Telegram accounts with no public @username — nothing to
capture. The fix is **display**: every actor-facing API projection + the FE must
label an actor as `current_handle or current_display_name or "id:"+platform_userid`,
never the bare numeric id. (e.g. `8595058147` → `Nicole Lee`.) One-line resolver,
apply everywhere an actor is rendered (linkage rows, graph nodes, actor lists).

The genuinely valuable handles remain the **in-body contact handles** (Component B) —
often richer than the poster's own (frequently absent) username.

## 5. How the pieces fit / order of work

1. **C first** (labeling resolver) — trivial, immediate operator relief.
2. **A** (copypasta detector, phase-1 exact-masked) — stops the linkage graph being
   flooded with false `shared_author` edges; ships the spam-template leaderboard.
3. **B** (indicator extraction + `shared_infra` linker) — the real intel: crews by
   operational overlap. Depends on A's masking to also emit the varying handles.
4. Verifier stays authorship-only and now runs on a **clean** (de-templated) corpus,
   so GI/NCD finally have signal instead of copypasta.

Own worktree; atomic `--no-ff` merge. Schema changes are pre-public: `rm data/*.db
&& eyenet init` (two new tables + one nullable column + `actor_indicator`).

## 6. Deferred / non-goals
- Near-dup MinHash (phase-2 A) until exact-masked demonstrably misses.
- BTC/phone extraction until the handle/TRX/EVM set proves insufficient.
- Cross-source (Matrix/etc.) indicator linking — the extraction seam is generic;
  each collector emits the same `actor_indicator` rows, so it comes for free as
  sources land.
