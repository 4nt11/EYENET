# Improvements, tiered by effort (with references)

Rule of this doc: a capability is "built" ONLY if a `file:line` backs it. No
citation = it does not exist = it goes in a build tier. Dr. Ragesworth, 2026-10-14.

Legend: BUILT (ship it / wire it) · HOURS · DAYS · WEEKS-MONTHS.

---

## Tier 0 — Already built, use what exists (cite or it's a lie)

| Proposed item | Status | Reference |
|---|---|---|
| Circadian fingerprint (hour / hour-dow / dow histograms, quiet span) | BUILT | `eyenet/sensor/primitives/circadian_hour_histogram.py:19`, `circadian_hour_dow_histogram.py:20`, `circadian_dow_histogram.py:19`, `circadian_quiet_span.py:19` |
| Timezone inference from circadian signal (offset + candidate zones, dual-signal zone_best) | BUILT | `eyenet/engine/timezone_inference.py:155` (`infer_timezone`), dataclass `:94` |
| Account meta (first/last seen, active days, msg/day, span) for lifecycle | BUILT | `eyenet/sensor/primitives/meta_first_seen_ts.py:23`, `meta_last_seen_ts.py:18`, `meta_active_days.py:18`, `meta_msg_per_day.py:21`, `meta_corpus_span_days.py:19` |
| Contact-handle / wallet pivoting as a LINKAGE signal | BUILT | `eyenet/linker/infra_linker.py:63` (`propose_infra_edges`), extractor `eyenet/linker/indicators.py:32` |
| Template / copypasta reuse detection (masked fingerprint) | BUILT | `eyenet/linker/copypasta.py:55` (`template_fingerprint`), `:41`, `:61` |
| Onion / domain artifact extraction | BUILT | `eyenet/sensor/discovery/url_extraction.py:39` (`_ONION_RE`), `:78` |
| EXIF extraction (sandboxed, attacker-controlled values) | BUILT | `eyenet/classifier/extract/_workers/image_meta_worker.py:39`, wired `eyenet/classifier/extract/__init__.py:101` |
| Typo signature + punctuation style (keyboard/typography seed) | BUILT | `eyenet/sensor/primitives/typo_signature.py:31`, `punctuation_style.py:23` |
| Dialect/region markers (L1 seed) | BUILT | `eyenet/sensor/primitives/dialect_region.py:41` |
| Authorship verifiers (compression distance, general impostors) | BUILT | `eyenet/verifier/verifiers/compression_distance.py:31`, `general_impostors.py:31` |
| Simhash comparators (char/fn-word/pos/opt-grammar hamming) | BUILT | `eyenet/linker/comparators/char_ngram_simhash_hamming.py:24` (+3 siblings) |

What's NOT here yet, even in built categories: holiday-absence, burstiness,
circadian-as-comparator, on-chain clustering, pHash. Those are below.

---

## Tier 1 — A couple hours (extends an existing seam, no new dep)

- **Extend `extract_indicators` to XMR/BTC/PGP-fingerprint/email/Session/Tox/Jabber/hashes.**
  Today it's handle + t.me + TRON + EVM only (`eyenet/linker/indicators.py:21-24`).
  Add regexes, `infra_linker.py:63` consumes them for free. Highest ROI on the list.
- **Dormancy -> reactivation flag.** Pure function over existing `meta.first_seen_ts` /
  `meta.last_seen_ts` / `meta.active_days`. No new primitive storage.
- **Circadian-similarity comparator.** The histograms exist (`circadian_hour_histogram.py:19`);
  add one `Comparator` (cosine/EMD over the vector) next to `comparators/char_ngram_simhash_hamming.py:24`.
  This turns an existing primitive into a LINKAGE feature, nearly orthogonal to style.
- **BBCode-usage primitive.** Same shape as `punctuation_style.py:23`; count tag frequencies.
- **Cross-forum timestamp-proximity query.** Copypasta fingerprints (`copypasta.py:55`) +
  message timestamps already stored; a read-time query flags same-template ads posted within N minutes.

## Tier 2 — Days (new primitive/module + calibration, maybe one new dep)

- **Burstiness / inter-arrival primitive.** New primitive + calibration grid (mirror `calibration/simhash_grid.py`).
- **Holiday-absence signal.** Calendar tables (Orthodox / Ramadan / Lunar NY) + absence test over
  the hour-dow histogram. Pairs with `timezone_inference.py` for culture-locking.
- **pHash / dHash image reuse.** New `imagehash` dep; hook the extract pipeline that already
  reads images (`classifier/extract/__init__.py:129`). EXIF path proves the plumbing exists.
- **Signature / ASCII-art reuse.** Variant of `copypasta.py` normalization for sig blocks.
- **LLM/GLiNER structured ad extraction (sold/price/breach/sector/country).** NOT built: GLiNER is
  only `development/GLINER-DOC.md` (untracked POC), no `eyenet/` import; presidio PII map
  (`eyenet/classifier/presidio/_default_pii_map.toml`) is PII, not ad-schema. New schema + extractor + price time-series.
- **BERTopic over time.** New dep; run over the stored corpus. Service emergence/death.
- **Survival analysis (time-to-first-complaint, exit-scam precursors).** `lifelines` dep +
  labeled complaint/ban events. No event labels exist today.
- **Graph backbone (disparity filter) + Leiden.** NO graph lib in `pyproject.toml`
  (checked: no networkx/igraph/leidenalg). Export from graph store (`storage/repository.py:1591-1645`),
  run offline. Backbone first, then community detection.
- **LUAR contrastive authorship embeddings (low end of DAYS).** The gap that matters: simhash is
  DISABLED for Spanish (CLAUDE.md §5). New model + a `Comparator` + verifier wiring +
  calibration. Single highest-value linkage upgrade for short Spanish texts.
- **L1 identification / MT-translation detection.** `dialect_region.py:41` is the seed; L1 and
  perplexity-vs-monolingual-LM need a model and a monolingual LM. New work.

## Tier 3 — Weeks to months (research, external data, or new infra)

- **Change-point stylometry within one account's timeline.** Inverts the current cross-account
  comparison. Needs per-account temporal windowing + `ruptures`-style detection + a fresh calibration
  of false-positive rate (a sold account vs a mood swing). Careful: forensic claim.
- **Graph role classification (vendor/buyer/escrow/shill/ripper) + broker/structural-hole detection.**
  Needs thread-position features + a labeled set + motif detection on the backbone graph.
- **Link prediction / node2vec / GNN for candidate identities.** Embedding training + serving infra.
- **On-chain wallet clustering (common-input, exchange/mixer flows).** External chain data/API,
  a whole subsystem. Extraction (Tier 1) is the prerequisite, not this.
- **Hawkes processes for cross-forum campaign diffusion.** Niche, research-grade.
- **Process mining (thread as act sequence -> scam grammar + early detector).** Act labeling is the
  hard part; the grammar is downstream.

---

## The one-line verdict

Your "best signal" (artifact pivoting) is already wired (`infra_linker.py:63`) and
one regex edit from 3x coverage (Tier 1). Your biggest GAP is Spanish authorship,
where simhash is off by design, so LUAR (Tier 2) is the real prize, not the graph
hairball. Do Tier 1 this week; it's almost free and keys off code you already shipped.
