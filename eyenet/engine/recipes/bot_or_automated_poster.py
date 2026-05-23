"""Recipe: bot_or_automated_poster.

An actor whose message stream is mechanically templated: extremely high
initiation rate (almost never replies) AND tight message-length variance
(templated content). Calibrated against SangMata_beta_bot in the Rutify
corpus (the only confirmed bot in the labeled set).

CALIBRATION (M5 / Rutify 2026-05-22):

* Axes (operator-locked):
    ``init_rate >= 0.95``
    AND ``message_length_variance_class == "tight"``  (word-count CV < 0.5)
* On the 74-actor labeled set: TP=1, FP=0, FN=0, P=1.000, R=1.000, F1=1.000.

Axis selection rationale:

* ``init_rate`` (>= 0.95): SangMata is at 1.000 (never replies). Human
  cohort: p90=0.83, max=0.94. Threshold sits cleanly above the human
  ceiling.
* ``message_length_variance_class`` (== "tight"): SangMata's word-count
  CV is 0.111 (every message templated as "User X changed name to Y").
  Human cohort: min=0.535. Zero humans land in the "tight" bucket
  (primitive's CV<0.5 cutoff). Strongest discriminator we have.

Axes NOT used and why:

* ``inter_msg_cv`` (clockwork-cadence gate): SangMata is event-driven,
  not clockwork. Its inter_msg_cv is 1.67 — well into the human range.
  Any clockwork gate would miss this entire bot class.
* ``mattr`` (lexical diversity): SangMata's MATTR is 0.49, well below
  the human cohort min of 0.82, so MATTR DOES discriminate. Reserved as
  a future tertiary axis for tightening; not in v0 to keep the recipe
  surface minimal.
* ``punctuation_style`` / ``typo_signature``: M3 primitives but no
  calibration data on their discriminative value yet.
"""

from __future__ import annotations

from eyenet.contracts.attribution import ProfileRow, RecipeResult

from ._base import get_slot_value, slots_present

NAME: str = "bot_or_automated_poster"
VERSION: str = "0.2"
REQUIRED_SLOTS: tuple[str, ...] = (
    "interaction_summary.conversation_initiation_rate",
    "stylometric_summary.message_length_variance_class",
)

# ---- Calibrated thresholds (M5 / Rutify 2026-05-22) -----------------------
MIN_INITIATION_RATE: float = 0.95
"""Bot initiates >= 95% of its own messages (almost never replies)."""

LENGTH_VARIANCE_TIGHT_VALUE: str = "tight"
"""The "tight" bucket of message_length_variance_class (word-count CV < 0.5).
SangMata is at CV=0.111. No labeled human falls in this bucket."""

MIN_OBSERVATION_COUNT: int = 30
"""At least N observations for reliable detection."""
# ---------------------------------------------------------------------------


def evaluate(profile: ProfileRow, derived_from_observation_count: int) -> RecipeResult:
    if not slots_present(profile, REQUIRED_SLOTS):
        return RecipeResult(
            matches=False,
            confidence=0.0,
            reasoning={"skip_reason": "required_slots_absent", "calibrated": True},
        )

    init_rate = get_slot_value(profile, "interaction_summary.conversation_initiation_rate")
    length_var = get_slot_value(profile, "stylometric_summary.message_length_variance_class")

    if not isinstance(init_rate, float | int):
        return RecipeResult(
            matches=False,
            confidence=0.0,
            reasoning={"skip_reason": "init_rate_not_numeric", "calibrated": True},
        )
    if not isinstance(length_var, str):
        return RecipeResult(
            matches=False,
            confidence=0.0,
            reasoning={"skip_reason": "length_variance_not_string", "calibrated": True},
        )

    init_rate = float(init_rate)
    high_init = init_rate >= MIN_INITIATION_RATE
    tight_length = length_var == LENGTH_VARIANCE_TIGHT_VALUE
    matches = high_init and tight_length

    count_confidence = min(1.0, derived_from_observation_count / MIN_OBSERVATION_COUNT)

    if matches:
        # Init-rate signal strength: how far above the boundary, scaled.
        init_signal = (init_rate - MIN_INITIATION_RATE) / (1.0 - MIN_INITIATION_RATE)
        # The length-variance enum is binary at recipe level (tight or not).
        # When matched, treat as full signal (1.0) and let count_confidence
        # carry the weight at low observation counts.
        length_signal = 1.0
        signal_confidence = (init_signal + length_signal) / 2.0
        confidence = round(count_confidence * signal_confidence, 4)
    else:
        confidence = 0.0

    return RecipeResult(
        matches=matches,
        confidence=confidence,
        reasoning={
            "calibrated": True,
            "calibration_corpus": "rutify-full-2026-05-02",
            "init_rate_observed": round(init_rate, 6),
            "length_variance_observed": length_var,
            "threshold_min_initiation_rate": MIN_INITIATION_RATE,
            "threshold_length_variance_value": LENGTH_VARIANCE_TIGHT_VALUE,
            "observation_count": derived_from_observation_count,
        },
    )


class BotOrAutomatedPosterRecipe:
    name = NAME
    version = VERSION
    required_slots = REQUIRED_SLOTS

    def evaluate(self, profile: ProfileRow, derived_from_observation_count: int) -> RecipeResult:
        return evaluate(profile, derived_from_observation_count)


__all__ = [
    "LENGTH_VARIANCE_TIGHT_VALUE",
    "MIN_INITIATION_RATE",
    "MIN_OBSERVATION_COUNT",
    "NAME",
    "VERSION",
    "BotOrAutomatedPosterRecipe",
]
