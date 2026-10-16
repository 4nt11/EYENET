# STYLOMETRY_MFW_PLAN.md — incremental per-actor MFW profiles

Status: PLAN (no code yet). Owner decision points in §12.

Purpose: give the Verifier a cheap, interpretable, language-agnostic authorship
signal: a per-actor distribution of Most Frequent Words (MFW), maintained
**incrementally** on ingest and compared on demand. Complements (does not
replace) LUAR. See `[[project_luar_stylometry_poc]]` (full-distribution Burrows
already beat the shipped simhashes) and CLAUDE.md §5 (locale-agnostic primitives).

---

## 1. Core idea

- MFW is **data-driven**, not a hand-built function-word list. The top-N most
  frequent tokens *in the corpus* ARE the function words, in every language,
  automatically. No per-language dictionaries. This is the language-agnostic
  property and the reason the design scales past Spanish.
- Per-actor token **counts are additive** (a commutative monoid), so maintenance
  is incremental view maintenance (IVM): ingest a message, `+=` a few counters,
  never recompute the corpus. This is the whole efficiency argument (fits <8GB).
- **Three** comparators off the SAME stored counts, all shipped (decided
  2026-10-16: cheap enough that there is no reason to pick one; they fail in
  opposite data regimes, so ensemble):
  - **MFW-cosine** — raw relative-frequency cosine. Strongest at higher token
    volume.
  - **Burrows's classic Delta** — z-score + Manhattan. Stronger on LITTLE data.
  - **Cosine-Delta** (Smith-Aldridge) — z-score + cosine.

**This GENERALIZES the existing predecessor, it does not start from scratch.**
`eyenet/sensor/primitives/function_word_distribution_top50.py` already does
function-word relative frequencies, BUT: (1) hardcoded EN/ES-only word lists (no
CJK/Thai/Russian), (2) Latin-only regex tokenizer, (3) it collapses the
distribution into a lossy 64-bit `simhash64`. That simhash is exactly why
`[[project_luar_stylometry_poc]]` found full-distribution Burrows beat it. This
plan keeps the FULL distribution (no simhash), makes the vocab data-driven +
per-locale, swaps the tokenizer for ICU, and maintains it incrementally. Reuse:
the `MIN_MESSAGES=30`/`MIN_TOKENS=500` floor precedent, and `_ngrams()` from
`character_ngram_simhash.py` (2-line sliding window, already language-agnostic)
for the char-n-gram comparator. **Drop `simhash64` everywhere in this subsystem**
— it is the lossy step that killed precision.

---

## 2. Tokenization + locale (CJK/Thai are IN SCOPE)

Whitespace tokenization is rejected: Chinese/Japanese/Thai have no word spaces,
and those actors exist in the corpus (to be confirmed by the backfill's locale
histogram — §5). **DECIDED 2026-10-16: ICU is in** (a dependency that earns its
keep gets added), as the word-level primary. Char-n-grams ship too (we already
have the extractor), as the segmentation-free comparator and the CJK/short-text
hedge, benchmarked against ICU words on the M5 grid.

- **Primary — ICU word segmentation.** One dependency (PyICU / libicu) does
  Unicode-aware, dictionary-backed word breaking across every script including
  CJK and Thai. Yields real "words" for the analyst bar-chart. Language-agnostic
  by one tool, not N tools. Replaces the Latin-only regex in the old primitive.
- **Also shipped — character n-gram MFW (segmentation-free).** Top-N character
  3/4-grams via the existing `_ngrams()` in `character_ngram_simhash.py`.
  Sidesteps segmentation entirely (so it never needs ICU), is empirically a
  top-tier authorship feature (captures morphology + function words + punctuation
  habits), and is the most robust on short texts. Less pretty on screen, so it
  is the comparator, not the default viz. The M5 grid decides its weight,
  especially on CJK and short messages.

**Locale** is detected per message (existing §5 path; for CJK/Thai the script is
itself a strong locale signal). It buckets every table below, so Spanish actors
compare on the Spanish top-N and Chinese on the Chinese top-N, and cross-locale
pairs correctly have no shared basis (not comparable = the truth, not a bug).

---

## 3. Data model

**Two NEW tables** (the exactly-once watermark reuses the existing `corpus_cursor`,
§4 — no third table, no `message` column). Final column lists at build time;
migration per `[[reference_adding_a_column_migration_convention]]`:

1. **`actor_mfw_count`** — the per-actor sparse distribution.
   Key `(actor_id, locale, token)`, value `count`. Tail-pruned (§6).
2. **`actor_mfw_profile`** — per-actor, per-locale meta.
   `(actor_id, locale)` -> `total_tokens`, `message_count`, `last_message_ts`.
   (The processing watermark lives in `corpus_cursor` keyed by
   `(actor_id, primitive_name)`, NOT here — §4.)
3. **`locale_token_freq`** — the global per-locale frequency.
   `(locale, token)` -> `count`, `doc_freq` (# distinct actors, for Delta /
   optional tf-idf weighting). The **top-N emerges here** via `ORDER BY count
   DESC LIMIT N`; cache it per locale, refresh on a tick.

Population stats for Delta (per-locale, per-feature mean/std of relative
frequency across actors) are maintained incrementally (Welford) OR recomputed
periodically — kept OFF the ingest hot path (§7).

---

## 4. Incremental maintenance (ingest)

**Exactly-once is a hard requirement** and the one real correctness risk: counts
are additive, so counting a message twice inflates the actor's distribution and
silently corrupts an authorship verdict (unlike the idempotent artifact dedup,
where a re-store is a no-op).

**DECIDED 2026-10-16: watermark via the EXISTING `corpus_cursor`, not a new
table and not a `message` column.** Option A (fold into the live discovery pass)
is out: that pass subscribes `raw.message.>` on **NATS core** (`eyenet/bus/
nats.py`, "core for v0") = at-most-once / fire-and-forget — never redelivers, but
can silently DROP messages, so the live bus is not a reliable count source. The
persisted `message` table is the source of truth, walked by cursor.

**We already have the exact mechanism — reuse it, don't reinvent.**
`corpus_cursor` (`eyenet/models/corpus.py`) is PK `(actor_id, primitive_name)`
-> `last_processed_msg_ts` + `last_processed_msg_id`, read/written via
`get_cursors_bulk(actor_id, names)` / `set_cursors_bulk(...)`. The
**StylometricSensor already drives every window primitive off it** exactly as a
watermark: fetch an actor's messages since the cursor, run the primitive, advance
the cursor. **MFW is just another primitive.** It registers under a
`primitive_name` (e.g. `stylometric.mfw`), gets a per-actor cursor row for free,
and is computed per-actor (which is also how the distributions are keyed), so the
sensor pattern fits natively.

Per actor, per walk: load cursor -> fetch messages since `last_processed_msg_id`
-> detect locale -> segment (ICU) -> ONE transaction incrementing
`actor_mfw_count` + `locale_token_freq` + `actor_mfw_profile` AND advancing the
cursor via `set_cursors_bulk`. Re-running is idempotent (already-counted messages
are behind the cursor), so crash/retrigger never double-counts and the live bus's
at-most-once gaps self-heal on the next walk.

**Why not the `message` nullable-counted column** (considered 2026-10-16): it is
race-free, but it (1) UPDATEs the evidence table for derived bookkeeping (MVCC
churn at 155k+, and we don't mutate operator-grade evidence rows for housekeeping)
and (2) is MFW-specific — it would breed `mfw_counted`/`circadian_counted`/…
barnacles on the core table. `corpus_cursor` is the general, already-shipped home.

**Race (inherited, acceptable):** a message can commit with an id just below the
cursor after it advanced (out-of-order commits). The StylometricSensor already
lives with this for every primitive; MFW inherits the same posture (and a 500+
token profile shrugs off one missed message). If race-free ever matters, revisit
then — not by writing the evidence table.

Incremental upsert (`INSERT ... ON CONFLICT DO UPDATE SET count = count + :n`) is
**dialect SQL** -> lives in the concrete backend per CLAUDE.md §2.3 Rule 1, the
mixin declares + `raise NotImplementedError`. Batch the per-message increments
(`*_bulk`) to dodge async session overhead (§2.8).

---

## 5. Backfill (seed the existing corpus)

An incremental aggregate needs a one-shot seed over history, exactly like
`artifact-backfill`: keyset page over messages, segment, bulk-increment,
exactly-once. New CLI `eyenet mfw-backfill`. **Its first output is the locale
histogram** — that is the data that proves (or disproves) the CJK/Thai actor
claim. Keyset + bulk, never OFFSET + per-row (the 15h lesson).

---

## 6. Pruning (bounds memory)

Zipf: the long tail is hapaxes, irrelevant to MFW (head-only). A periodic prune
(tick or `eyenet mfw-prune`) drops per-token rows below a count/age threshold in
`actor_mfw_count` and `locale_token_freq`. `total_tokens` is a separate counter
and stays exact (pruning storage of rare tokens never corrupts the denominator).
Never prune anything currently in a locale's top-N. This is what keeps it in
<8GB.

---

## 7. Comparison (Verifier comparator)

Given two actors in the same locale:
1. Gate on the **token floor** (`total_tokens >= min`); else abstain. A
   distribution from 40 tokens is noise with confidence (the wallet-hash lesson).
2. Load each actor's counts for the locale top-N; build relative-frequency
   vectors aligned on that top-N.
3. Compute **all three**: MFW-cosine (raw), classic Burrows-Delta, Cosine-Delta
   (z-score by the per-locale population mean/std). Ensemble/pick by data regime.
4. Return all three distances + the **basis snapshot** (top-N vocab + stats used).

**Operator-grade evidence:** persist the basis snapshot with any linkage verdict
the Verifier emits, so a verdict is reproducible even as the corpus (and thus the
top-N) drifts. A moving basis that can't be reconstructed is a verdict a defense
tears apart.

Thresholds are **per-locale**, calibrated on the M5 grid; pull the winning N +
Delta variant from `development/poc-luar`.

---

## 8. Visualization (analyst surface)

- Per-actor MFW distribution: bar chart of top-N relative frequencies.
- Inter-actor Delta/cosine **heatmap** for a candidate cluster.
- Lives in the actor view / Verifier UI. Interpretable linkage evidence ("both
  over-use `pero`, under-use `que`") — the thing LUAR embeddings can never show.

---

## 9. Dependencies

- **PyICU** — IN (decided 2026-10-16). Needs the `libicu` system lib in the
  Docker runtime + builder stages (same pattern as `libolm3` for matrix-nio;
  see [[project_dockerfile_optimization_todo]]). Declare direct in pyproject +
  uv.lock. The char-n-gram comparator adds no dep (reuses `_ngrams`).

---

## 10. Calibration & validation

- Per-locale thresholds on the M5 calibration grid; Spanish first (existing
  target), then whatever the backfill locale histogram surfaces.
- Benchmark Option A vs B on labeled `poc-luar` pairs, especially CJK/short-text.
- Same-register is MFW's strength; cross-register is where LUAR wins — route
  accordingly, don't force one tool to do both.

---

## 11. Storage-layer compliance (non-negotiable)

- Production reads via `get_repository()` typed `BaseRepository` (§2.2).
- Generic ORM (counts read, profile read) in the sqlmodel mixin; the `ON CONFLICT
  DO UPDATE count = count + n` upsert overrides on the concrete backend (§2.3
  Rule 1). Postgres-primary per `[[project_sqlite_deprioritized_postgres_primary]]`.
- Tests type against `BaseRepository` + `get_repository(in_memory=True)` (§3).

---

## 12. Decisions

1. **Tokenizer — RESOLVED 2026-10-16:** ICU word-seg (primary, interpretable) AND
   char-n-grams (reuse `_ngrams`, seg-free, CJK/short-text hedge). Both ship;
   M5 grid weights them. ICU dependency approved.
2. **Exactly-once — RESOLVED 2026-10-16:** reuse the existing `corpus_cursor`
   per-`(actor, primitive)` watermark (the StylometricSensor pattern). NOT a
   `message` column (mutates evidence, MFW-specific), NOT a new table.
3. **Comparators — RESOLVED 2026-10-16:** ship all three (MFW-cosine, classic
   Burrows-Delta, Cosine-Delta); ensemble by data regime.
4. **Still open — Delta N + variant weights:** inherit the starting config from
   `poc-luar` rather than re-derive, then tune on the M5 grid.
5. **Still open — v1 scope:** counts + backfill + comparator first; analyst viz
   + the ICU-vs-n-gram calibration as a follow phase?

---

## 13. Phasing

1. Schema + storage methods (incremental upsert on concrete backend, bulk).
2. Tokenizer + locale bucketing (ICU).
3. Ingest (exactly-once) + `mfw-backfill` CLI (emits the locale histogram).
4. Prune job.
5. Verifier comparator (cosine + Delta) + population-stat maintenance.
6. Analyst viz.
7. Calibration (per-locale thresholds, A-vs-B experiment).
