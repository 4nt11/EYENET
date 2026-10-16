# poc-luar: authorship linkage for EYENET (LUAR vs classics vs shipped comparators)

Goal, in one sentence: can we reliably say **"actor A and actor B are the same
person"** from linguistic analysis of their messages, on EYENET's real data,
including Spanish?

This PoC answers that with measured numbers, compares the neural LUAR model
against classical stylometry AND against EYENET's own shipped comparators, and
lands on a concrete, cheap recommendation. Nothing here is wired into `eyenet/`;
it is all standalone under `development/poc-luar/`.

Date: 2026-10-14. Model env: torch 2.14.1+cu130, transformers 5.16.1, Python 3.14.

---

## TL;DR verdict

1. **On the test that matters most (cross-PLATFORM: same actor, different forum /
   Telegram, author-centric), LUAR DOMINATES** - AUC 0.976, EER 0.067, R@1 0.77
   on 60 persons, versus the best classic at AUC 0.87 / R@1 0.5. The surface
   classics collapse across platforms (char n-grams track forum markup/BBCode,
   function words track register; both change per forum). This is the real
   justification for the neural model - invisible on same-topic tests, decisive
   here. (On the weaker cross-GROUP Telegram test LUAR only narrowly led, AUC
   ~0.92; the harder the genuine context shift, the more LUAR separates.)
2. **EYENET's shipped stylometric comparators are the WORST methods tested**
   cross-context (`function_word_simhash` AUC 0.75-0.85 / EER 0.20-0.33;
   `char3_simhash` AUC 0.88 / EER 0.17). The 64-bit simhash quantization throws
   away signal: the **full-distribution version of the same features beats the
   simhash version every time.**
3. **A free CPU method is nearly as good as LUAR cross-context**: Burrows's Delta
   on full function-word frequencies (AUC 0.92, EER 0.11, ~zero topic
   degradation). For the small operator, that alone is a large upgrade over what
   ships today - no GPU, no model.
4. **Centering is mandatory for LUAR.** Raw LUAR cosines are anisotropic
   (different authors score ~0.6-0.98); subtract the corpus mean and
   different-author cosine collapses to ~0. This single step took Spanish
   split-half EER from 0.167 to 0.033.
5. **We cannot yet validate any of this *for Spanish specifically*** - the corpus
   has almost no same-person-across-groups ground truth inside Spanish target
   groups (literally ~1 cross-group CHAT person). The cross-context evidence is
   multilingual. The Spanish-specific evidence is the weaker split-half test.

---

## What "same person" means here (the protocol)

A verifier takes two piles of an actor's text and returns a score that they are
the same human, with a threshold that yields known error rates. Two eval regimes:

- **Same-context (easy):** split one actor's messages temporally (early half =
  query, late half = target). Same person, same group, so topic is roughly held
  constant. Measures re-identification, not the operational problem.
- **Cross-context (the real job):** same person (`platform_userid`) posting in
  two DIFFERENT groups. Pile A (group X) vs pile B (group Y). Different topic,
  audience, time. This is what EYENET actually faces: an actor resurfacing in a
  new place. **This is the test that separates topic-leakage from real style.**

Ground truth = Telegram `platform_userid` (a user id; same id across groups is the
same human even if the handle changed). Negatives = different user ids.

Metrics:
- **EER** (Equal Error Rate): slide the threshold until false-accept rate ==
  false-reject rate; that balanced error is the EER. Lower is better. The number
  to care about for a thresholded verifier. 0.07 = 7% error at the balance point.
- **AUC**: P(a same-author pair scores higher than a different-author pair).
  0.5 = chance, 1.0 = perfect. Directly comparable to the M5 Rutify grid.
- **R@1**: fraction of queries whose nearest target is the correct author (hard
  needle-in-haystack; punishes crowded candidate pools).
- **separation**: mean(same) - mean(diff). The most honest raw signal.

---

## Methods compared

Shipped EYENET comparators (reproduced faithfully, standalone, cited in source):
- `eyenet_char3_simhash` - char-trigram freq -> 64-bit simhash -> Hamming
- `eyenet_fnword_simhash` - top-50 function-word rel-freq (ES/EN vote) -> simhash

Full distributions (no 64-bit quantization):
- `full_char3_js` - Jensen-Shannon divergence over char-trigram distributions
- `full_char4_jaccard` - Jaccard over char-4gram sets
- `burrows_delta` - z-scored top-word frequencies, Manhattan distance

Neural:
- `luar_centered` - LUAR-MUD episode embedding, mean-centered cosine

---

## Results

### Same-context split-half, 300 corpus-wide actors (the easy question)

| method | R@1 | EER | note |
|---|---|---|---|
| Burrows's Delta | 0.65 | 0.053 | |
| Jaccard char-4 | 0.69 | 0.030 | |
| JS/KL char-3 | 0.72 | **0.020** | a free counter beats LUAR here |
| LUAR-MUD centered | 0.67 | 0.023 | |
| LUAR-MUD raw (uncentered) | 0.67 | 0.024 | diff-cos 0.63: anisotropic |

Takeaway: on same-topic re-identification, cheap char-n-gram methods tie or beat
LUAR, because shared topic does the work. This test flatters the counters.

### Cross-context bake-off (the real question), n = 29 persons (min 8 msgs/context)

Confirmed stable at n=15 (min 12) and n=56 (min 5). Numbers below are the
cross-context column; lower EER / higher AUC better.

| method | AUC | EER | topic-robust (dAUC same->cross) | cost |
|---|---|---|---|---|
| **luar_centered** | **0.922** | **0.073** | yes (-0.021) | GPU + 500MB model |
| burrows_delta (full fn-words) | 0.916 | 0.107 | **yes (-0.001)** | CPU, ms |
| full_char4_jaccard | 0.908 | 0.172 | no (-0.023) | CPU, ms |
| full_char3_js | 0.892 | 0.135 | no (-0.025) | CPU, ms |
| eyenet_char3_simhash (SHIPPED) | 0.882 | 0.173 | - | CPU |
| eyenet_fnword_simhash (SHIPPED) | 0.813 | 0.216 | - | CPU |

### Author-centric cross-PLATFORM bake-off (the real use case), n = 60

Ground truth = same NORMALIZED handle on >=2 different sources (darkforums,
raidforums, pwnforums, breached.st, telegram), >=10 usable msgs per source.
Silver GT: handle-match across forums is strong but imperfect (handle squatting
exists), which if anything DEPRESSES measured accuracy. Cross-platform column,
lower EER / higher AUC better:

| method | AUC | EER | R@1 | note |
|---|---|---|---|---|
| **luar_centered** | **0.976** | **0.067** | **0.767** | dominant |
| distinctive_vocab (TF-IDF rare words, full) | 0.872 | 0.230 | 0.500 | best classic; beats shipped simhash of same feature |
| full_char4_jaccard | 0.864 | 0.201 | 0.567 | |
| full_char3_js | 0.814 | 0.235 | 0.567 | |
| eyenet_fnword_simhash (SHIPPED) | 0.776 | 0.270 | 0.250 | |
| eyenet_char3_simhash (SHIPPED) | 0.755 | 0.316 | 0.367 | |
| burrows_delta | 0.756 | 0.304 | 0.433 | strong on Telegram, WEAK cross-forum (register shifts) |

Operating point (FAR 5%, base rate 1 real link / 60 candidates): LUAR recall
0.867 / precision 0.227; `ENSEMBLE_free` (distinctive + char-3 JS) recall 0.617,
beating every single classic and both shipped comparators with no GPU.

Key shifts from the Telegram cross-group result: (1) LUAR goes from "narrow lead"
to "dominant" as the context shift gets more genuine; (2) Burrows (function words)
is NOT robust across forums, only across Telegram groups; (3) `distinctive_vocab`
- EYENET's own computed-but-unwired primitive - is the best free method,
confirming it is worth wiring.

### Operating point / the base-rate reality (comparator_poc.py)

AUC/EER describe the whole curve; an operator runs at ONE threshold. At a target
false-accept rate of 1% on the n=29 set (base rate = 1 real link per 29
candidates, 3.4%), precision-at-base-rate lands at only ~0.14-0.31 for EVERY
method, LUAR included. That is the base-rate fallacy: when true links are rare,
even a 1% impostor-accept rate yields more false accepts than true ones.

Consequence (and it confirms the design principle): the linguistic score is a
CANDIDATE FILTER that proposes links for corroboration (shared infra, timing,
social graph), never an auto-accept. A free ensemble (z-scored Burrows +
char-3 JS) roughly matched Burrows alone and did not clearly beat LUAR at this n;
ensembling is not free magic on 29 pairs.

Two hard conclusions:
- The shipped simhash comparators sit at the bottom. The full-distribution
  version of the SAME char-trigram feature beats its simhash (EER 0.135 vs 0.173);
  full function words (Burrows) crush the function-word simhash (EER 0.107 vs
  0.216). **64-bit Hamming quantization is leaving ~half the signal on the table.**
- Only LUAR and Burrows (function words) are genuinely topic-robust. The
  char-n-gram counters' advantage evaporates cross-context, exactly as theory
  predicts (char n-grams reward shared vocabulary = partly topic).

---

## EYENET's existing stylometry: inventory and gaps

Primitives EMITTED by the sensor (`eyenet/sensor/primitives/`):
char trigrams, POS bigrams, function-word top-50, distinctive (rare) vocabulary,
punctuation style, persistent-typo signature, vocabulary richness (MATTR),
dialect region (es-CL/AR/MX), optional-grammar (subjunctive, clitic, relative),
evaluative morphology (diminutives), plus circadian ACTIVITY histograms.

Comparators WIRED into the Linker (`eyenet/linker/comparators/`): only **4** -
`char_ngram_simhash`, `function_word_simhash`, `pos_ngram_signature`,
`optional_grammar_signature`. All simhash/Hamming. `char_ngram` and
`function_word` are DISABLED for Spanish (M5 Rutify: AUC 0.68 / 0.55).

The gaps:
1. **Computed but never used for linkage:** `distinctive_vocabulary_signature`
   (its own docstring: "strong against context-shift"), `punctuation_style`
   ("survive topic changes"), `typo_signature` ("stable for consistent typists").
   The most context-robust features are extracted, stored, and ignored by the
   Linker. This matches our finding that topic-robustness is what wins
   cross-context.
2. **Lossy representation:** everything compares via 64-bit simhash Hamming. The
   PoC shows full distributions of the same features score materially better.
3. **No chronolectal / diachronic analysis.** `circadian_*` is activity timing
   (when), not language drift (how style changes over time). Not necessarily
   needed, but it is absent if ever wanted.

---

## Recommendations (three independent, shippable)

1. **Cheapest real win, no LUAR:** add full-distribution comparators (Burrows on
   function words + char-trigram JS) and wire the already-computed
   `distinctive_vocabulary_signature` / `punctuation_style` / `typo_signature`
   into the Linker. Stays CPU-only. Likely enough to re-enable Spanish linkage.
   Prototyped in `comparator_poc.py`.
2. **LUAR as an optional backend / cascade:** best accuracy, topic-robust, but
   adds torch + transformers + a 500MB model (heavy for the little guy). Run the
   cheap comparator first, call LUAR only to adjudicate borderline scores.
3. **Get Spanish cross-context ground truth** (operator-confirmed links, or more
   cross-group Spanish collection) before claiming either works for Spanish
   specifically. We are currently extrapolating from multilingual evidence.

---

## Files

- `luar_poc.py` - LUAR embedder + split-half verification + Spanish heatmap +
  exploratory within-channel multi-operator clustering.
- `classic_poc.py` - Burrows / Jaccard / JS-KL on the split-half protocol.
- `crosscontext_poc.py` - the bake-off (all methods incl. `distinctive_vocab`,
  reproduces shipped simhash comparators standalone). `--mode cross-source`
  (author-centric, same handle across platforms, silver GT) or `cross-group`
  (same user across Telegram groups).
- `comparator_poc.py` - prototype of recommendation 1: calibrated
  full-distribution comparator (incl. `distinctive_vocab`) with a threshold at a
  target FAR, plus a free ensemble. Same `--mode`.
- `out/` - report JSONs + `spanish_heatmap.png`.
- `.venv/` - system-site-packages venv (inherits torch/transformers; adds
  psycopg, einops, matplotlib, scikit-learn, termcolor).

## How to run

DB access is via `docker exec docker-postgres-1 psql` (Postgres is not
host-mapped). The password constant in the scripts is the local dev DB.

```
./.venv/bin/python luar_poc.py --groups both --max-authors 300
./.venv/bin/python classic_poc.py --groups both
./.venv/bin/python crosscontext_poc.py --mode cross-source --min-msgs 10   # author-centric, cross-platform
./.venv/bin/python crosscontext_poc.py --mode cross-group  --min-msgs 8    # same user across TG groups
./.venv/bin/python comparator_poc.py --mode cross-source --min-msgs 10 --far 0.05
```

## Caveats (read before quoting any number)

- n is small (15-56 cross-context persons). Directional and stable, not
  production calibration.
- Zero cross-context persons fall inside Spanish target groups; cross-context
  evidence is multilingual.
- same-vs-cross has a text-volume confound (same-context piles are half-size); the
  cross-context absolute column is the clean comparison and the one ranked on.
- Within-channel multi-operator clustering is exploratory: no `post_author`
  ground truth on this backfilled data (the signature capture postdates it).
