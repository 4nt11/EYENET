<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# EYENET Attribution Recipes (M3)

> **These recipes are EYENET-local.** They describe how the Engine converts
> BEHAVE-TEXT observations into `role_signal` verdicts. They are NOT part of
> BEHAVE-TEXT itself — the BEHAVE-TEXT taxonomy (`Observation` envelopes,
> primitive names, value shapes) is defined in `decnet-behave-text`.
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

## Role Recipes (M3)

### `lurker_or_observer`

**Source:** `eyenet/engine/recipes/lurker_or_observer.py`  
**Version:** 0.1  
**Required slots:** `interaction_summary.conversation_initiation_rate`

An actor who is present but almost never starts new threads. Minimal contribution
to group conversation topology.

**Signals used:**
- `conversation_initiation_rate` ≤ **`UNCALIBRATED_MAX_INITIATION_RATE`** (0.05)

> ⚠️ **UNCALIBRATED.** Threshold derived from first-principles reasoning, not the
> Rutify corpus. Replace with empirical values in M5 calibration. All thresholds
> ship as `UNCALIBRATED_*` constants; recipe reasoning carries `"calibrated": False`.

**Confidence:** scales with observation count and distance from threshold.

---

### `bot_or_automated_poster`

**Source:** `eyenet/engine/recipes/bot_or_automated_poster.py`  
**Version:** 0.1  
**Required slots:** `interaction_summary.conversation_initiation_rate`, `lexical_summary.mattr`

A poster operating with machine-like regularity: high initiation (always new
threads, never replies) AND low lexical diversity.

**Signals used:**
- `conversation_initiation_rate` ≥ **`UNCALIBRATED_MIN_INITIATION_RATE`** (0.95)
- `mattr` ≤ **`UNCALIBRATED_MAX_MATTR`** (0.65)

> ⚠️ **UNCALIBRATED.** The full recipe per BEHAVE-TEXT spec also uses
> `punctuation_style` consistency and `typo_signature` stability. Those
> primitives are implemented in M3 but not yet included in the threshold
> model — combining them requires calibration data from the Rutify corpus
> (M5). The note `"punctuation_style and typo_signature not yet included; see M5"`
> appears in every recipe reasoning dict.

**Confidence:** combined from initiation and MATTR signal strengths × observation count.

---

## Future Recipes (post-M5 calibration)

Per the BEHAVE-TEXT placeholder, candidates for M5+:

- `credential_broker` — high `content.transactional_language`, high `content.boasting_pattern`, broadcast attention.
- `low_skill_buyer` — low `lexical_summary.mattr`, slow response latency, high question formation.
- `group_admin` — high `conversation_initiation_rate` (moderates, not just posts), focused attention pattern.

These require observation primitives not yet implemented in EYENET.

---

## Status

M3 (2026-05-13): two recipes shipped. Thresholds are UNCALIBRATED first-principles estimates.  
M5: Rutify corpus calibration replaces all `UNCALIBRATED_*` constants.
