<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# EYENET Attribution Recipes

> **These recipes are EYENET-local.** They describe how the Engine converts
> BEHAVE-TEXT observations into `role_signal` verdicts. They are NOT part of
> BEHAVE-TEXT itself — the BEHAVE-TEXT taxonomy (`Observation` envelopes,
> primitive names, value shapes) is defined in the `behave-text` package.
>
> The Engine's `RoleSignal` type (declared in `eyenet/contracts/attribution.py`)
> is a recipe verdict, NOT a BEHAVE-TEXT primitive. BEHAVE-TEXT also uses the
> word "role" in some primitive namespaces (`network.governance_role_signal`,
> `content.role_signal`) — those are orthogonal observation primitives, not
> recipe verdicts.

---

## Engine Interface

**Consumes (bus):**
- `actor.observation.text.*` — BEHAVE-TEXT `Observation` envelopes, per-primitive subjects.
- `identity.label.applied` — operator-supplied ground-truth labels (future: override recipe verdict).
- `identity.engagement.authorized` — engagement whitelist (future).

**Emits (bus):**
- `attribution.profile.candidate` — every time a Profile slot is updated.
- `attribution.profile.current` — only when role_signal or a slot value materially changes.

**Persists:**
- `Profile` table (snapshot-per-update, `is_current` flip via `ProfileStore.upsert_current`).

---

## Profile Update Semantics

Every incoming observation maps to exactly one Profile slot (see `eyenet/engine/slot_mapper.py`).
A **profile snapshot** is created for each slot update: monotonic `version`, copy of all six
summary blocks with the changed slot patched. `ProfileCandidate` emits always; `ProfileCurrent`
emits only on material change.

Per-slot dict shape (enforced by the engine, not at the contract layer):
```json
{
  "value": "<primitive output>",
  "last_observation_id": "<UUID>",
  "derived_from_observation_count": 42
}
```

Optional per-slot fields:
- `"language"` — ISO 639-1 code surfaced on the `function_word_distribution_top50` slot
  (M5). Drives per-language threshold lookup in the Linker (see PLAN §M5).

---

## Primitive → Profile Slot Mapping

| Primitive (BEHAVE-TEXT name) | Namespace | Value kind | `Profile` slot |
|---|---|---|---|
| `stylometric.function_word_distribution_top50` | `stylometric` | HASH (simhash) | `stylometric_summary.function_word_simhash` |
| `stylometric.character_ngram_simhash` | `stylometric` | HASH (simhash) | `stylometric_summary.char_ngram_simhash` |
| `stylometric.distinctive_vocabulary_signature` | `stylometric` | HASH (simhash) | `lexical_summary.distinctive_vocab` |
| `lexical.vocabulary_richness` (MATTR) | `lexical` | NUMERIC | `lexical_summary.mattr` |
| `stylometric.message_length_class` | `stylometric` | ENUM (categorical) | `stylometric_summary.message_length_class` |
| `stylometric.message_length_variance_class` | `stylometric` | ENUM (categorical) | `stylometric_summary.message_length_variance_class` |
| `stylometric.punctuation_style` | `stylometric` | HASH | `stylometric_summary.punctuation_style` |
| `stylometric.typo_signature` | `stylometric` | HASH | `stylometric_summary.typo_signature` |
| `interaction.conversation_initiation_rate` | `interaction` | NUMERIC 0..1 | `interaction_summary.conversation_initiation_rate` |
| `meta.total_messages` | `meta` | NUMERIC | `temporal_summary.message_count` |
| `meta.corpus_span_days` | `meta` | NUMERIC | `temporal_summary.corpus_span_days` |
| `meta.msg_per_day` | `meta` | NUMERIC | `temporal_summary.msg_per_day` |
| `meta.active_days` | `meta` | NUMERIC | `temporal_summary.active_days` |
| `meta.activity_density` | `meta` | NUMERIC 0..1 | `temporal_summary.activity_density` |
| `meta.first_seen_ts` | `meta` | FREE_STRING (ISO 8601) | `temporal_summary.first_seen_ts` |
| `meta.last_seen_ts` | `meta` | FREE_STRING (ISO 8601) | `temporal_summary.last_seen_ts` |
| `meta.fingerprint_confidence` | `meta` | CATEGORICAL | `temporal_summary.fingerprint_confidence` |

---

## Recipe Protocol

All recipes implement `eyenet.engine.recipes._base.Recipe` (Protocol):

```python
class Recipe(Protocol):
    name: RoleSignal
    version: str
    required_slots: tuple[str, ...]  # dot-paths into profile summaries
    def evaluate(self, profile: ProfileRow, derived_from_observation_count: int) -> RecipeResult: ...
```

The engine evaluates all eligible recipes (those whose `required_slots` are populated),
picks the highest-confidence `matches=True` result, and writes `role_signal` + `role_confidence`
to the profile snapshot.

---

## Role Recipes (M5-calibrated)

All thresholds below come from the calibration grid against the Rutify
corpus on 2026-05-22. The committed artifact —
`tests/fixtures/calibration/rutify_calibration_baseline.json` — carries the
full confusion matrices and per-axis sweeps. The calibration test suite
(`pytest -m calibration tests/calibration/`) guards against drift.

### `lurker_or_observer`

**Source:** `eyenet/engine/recipes/lurker_or_observer.py`
**Version:** 0.3
**Required slots:** `()` (empty — OR-combinator; per-pattern guards inside `evaluate()`)

An actor who is present but almost never starts new threads. Two patterns,
OR-combined; either fires the recipe:

- **Pattern A — passive responder:**
  `conversation_initiation_rate` ≤ **`MAX_INITIATION_RATE`** (0.20)
- **Pattern B — long-tail occasional presence (M5.5):**
  `temporal_summary.msg_per_day` ≤ **`MAX_MSG_PER_DAY`** (2.0)
  AND `temporal_summary.corpus_span_days` ≥ **`MIN_CORPUS_SPAN_DAYS`** (7.0)

**Calibration:**
- Strategy: precision-floor (≥ 0.70), loosest thresholds meeting the floor.
- Labeled cohort: 74 actors / 5 lurkers / 22 chatty / 46 normal / 1 bot.
- Pattern A alone: P=1.000, R=0.400, F1=0.571.
- **Pattern A OR Pattern B (shipped M5.5): P=1.000, R=1.000, F1=1.000.**

**Confidence:** scales with observation count and distance from whichever
pattern's threshold is hit hardest (`max(signal_A, signal_B)`).
`reasoning["matched_patterns"]` lists which patterns fired (`["A"]`,
`["B"]`, or `["A", "B"]`). `reasoning["calibrated"] = True` since M5.

---

### `bot_or_automated_poster`

**Source:** `eyenet/engine/recipes/bot_or_automated_poster.py`
**Version:** 0.2
**Required slots:** `interaction_summary.conversation_initiation_rate`,
`stylometric_summary.message_length_variance_class`

A poster whose stream is mechanically templated: extremely high initiation
rate AND tight message-length variance.

**Signals used:**
- `conversation_initiation_rate` ≥ **`MIN_INITIATION_RATE`** (0.95)
- `message_length_variance_class` == **`"tight"`** (word-count CV < 0.5)

**Calibration:**
- Strategy: operator-locked axes (PLAN §M5, 2026-05-22). One bot in the
  corpus (SangMata_beta_bot) is the entire positive set; the labeled set
  cannot statistically calibrate a multi-axis recipe with N=1 positive,
  so axis values were fixed by inspection and tested empirically.
- Result on labeled set: P=1.000, R=1.000, F1=1.000.

**Axes NOT used and why:**
- `inter_msg_cv` (clockwork-cadence): SangMata is event-driven (cv=1.67),
  not clockwork. A cadence-gate would miss event-driven bots entirely.
- `mattr`: SangMata=0.49, human cohort min=0.82 — MATTR DOES discriminate
  but is reserved as a future tertiary axis. Not in v0 to keep the surface
  minimal.
- `punctuation_style` / `typo_signature`: M3 primitives but no calibration
  evidence yet of their discriminative value.

**Confidence:** combined from init-rate signal strength × observation count.
`reasoning["calibrated"] = True` since M5.

---

### `chatty_member`

**Source:** `eyenet/engine/recipes/chatty_member.py`
**Version:** 0.1
**Required slots:** `temporal_summary.message_count`
**Status:** LIVE (M5.5).

A highly active community participant: large total message volume, varied
content. Distinct from `bot_or_automated_poster` (templated) and
`lurker_or_observer` (passive).

**Signals used:**
- `msg_count` ≥ **`MIN_MESSAGE_COUNT`** (195)

**Calibration:**
- Strategy: precision-floor (≥ 0.70) on a single axis.
- Result on labeled set: P=1.000, R=0.955, F1=0.977. One false-negative
  (a borderline actor labeled `chatty_member` with msg_count=128).

**Slot wiring (M5.5):** `temporal_summary.message_count` is populated by
the `meta.total_messages` BEHAVE-TEXT 0.1.2 primitive. The slot-mapper
key is intentionally `message_count` (not `total_messages`) to match the
recipe's `REQUIRED_SLOTS` from M5.

---

## Calibration Provenance

| Artifact | Path |
|---|---|
| Baseline calibration | `tests/fixtures/calibration/rutify_calibration_baseline.json` |
| Per-actor stats (committed) | `tests/fixtures/calibration/rutify_actor_stats.csv` |
| Operator labels (committed) | `tests/fixtures/calibration/rutify_labels.toml` |
| Calibration test suite | `tests/calibration/` |
| Re-run grid | `uv run eyenet calibrate run --corpus … --labels … --out …` |

**Corpus:** Rutify Telegram group, 22,062 text messages, 409 senders,
Spanish (Chilean), 2026-05-02 snapshot. Gitignored; operator-only.

**Meta.* sensor primitives (M5.5):**

The eight BEHAVE-TEXT 0.1.2 `meta.*` primitives populate
`temporal_summary` for every actor:

| Primitive | Slot | Value type |
|---|---|---|
| `meta.total_messages` | `temporal_summary.message_count` | int |
| `meta.corpus_span_days` | `temporal_summary.corpus_span_days` | float (days) |
| `meta.msg_per_day` | `temporal_summary.msg_per_day` | float |
| `meta.active_days` | `temporal_summary.active_days` | int |
| `meta.activity_density` | `temporal_summary.activity_density` | float (0–1) |
| `meta.first_seen_ts` | `temporal_summary.first_seen_ts` | ISO 8601 |
| `meta.last_seen_ts` | `temporal_summary.last_seen_ts` | ISO 8601 |
| `meta.fingerprint_confidence` | `temporal_summary.fingerprint_confidence` | `low` \| `medium` \| `high` |

These primitives are corpus-level (not window-level): their
`PrimitiveSpec.requires_full_corpus = True` causes the sensor to pass
the actor's full history rather than the since-cursor delta. Bodies
fetch is skipped (timestamps only).

`fingerprint_confidence` cutoffs are EXTRACTOR-DEFINED per the
BEHAVE-TEXT spec; EYENET's v1 heuristic
(`high`: ≥100 msgs AND ≥7 active days; `medium`: ≥30 msgs AND ≥2 active
days; `low`: otherwise) is pinned by the source-label suffix
`#confidence-v1`.

---

## Simhash Linker (status: DISABLED for Spanish)

While not a "recipe" in the strict sense, the linker comparator thresholds
share the same calibration path. The M5 grid found that
`function_word_distribution_top50` and `character_ngram_simhash` on short
Spanish chat have AUC=0.55 and 0.68 respectively — too overlapping to
support a precision ≥ 0.70 operating point.

`LinkerThresholds` defaults ship with:
```python
function_word_simhash_hamming_per_lang = {"es": None}
char_ngram_simhash_hamming_per_lang   = {"es": None}
```

`None` = "explicitly disabled for this language; skip the comparator."
Other languages still use the language-blind defaults (8 / 10 bits). The
long-term fix is `minhash-with-shingles` in BEHAVE-TEXT 0.0.2, which is
expected to give a separable distribution on short Spanish text.

Until then, Spanish linkage is driven by:
1. The recipe layer (interaction stats — these calibrate cleanly).
2. The planned LLM-Confirmer service (post-M5 — consumes
   `attribution.linkage.proposed`, samples evidence_refs from both actors,
   asks an LLM "same author?", emits `attribution.linkage.{confirmed,rejected}`).

---

## Future Recipes (post-M5)

These need observation primitives not yet implemented in EYENET:

- `credential_broker` — high `content.transactional_language`, high `content.boasting_pattern`, broadcast attention.
- `low_skill_buyer` — low `lexical_summary.mattr`, slow response latency, high question formation.
- `group_admin` — high `conversation_initiation_rate` (moderates, not just posts), focused attention pattern.

---

## Status

- M3 (2026-05-13): two recipes shipped. UNCALIBRATED first-principles thresholds.
- M5 (2026-05-23): both recipes recalibrated against Rutify. Third recipe
  (`chatty_member`) added. Spanish simhash linkage disabled with explicit
  sentinel. Calibration test suite live. Provenance pinned by artifact sha256.
- M5.5 (2026-05-23): eight BEHAVE-TEXT 0.1.2 `meta.*` primitives wired
  through sensor → slot_mapper → `temporal_summary`. `chatty_member`
  activates; `lurker_or_observer` Pattern B ships, lifting recall to
  1.000 on the labeled set.
