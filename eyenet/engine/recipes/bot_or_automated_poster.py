"""Recipe: bot_or_automated_poster.

An actor posting with machine-like regularity: extremely high initiation rate
(posts new threads, almost never replies), low lexical diversity (MATTR), and
stable character-ngram fingerprint across messages (simhash distance near 0).

THRESHOLDS: all values are UNCALIBRATED. Rutify corpus grid (M5) will replace
these. Reason dict carries `"calibrated": False` on every evaluation.

Note: the full BEHAVE-TEXT recipe for this class also uses `punctuation_style`
consistency and `typo_signature` stability. Those primitives are shipped in M3
but not yet used here because the recipe confidence model for combining them
requires calibration data. Added to `REQUIRED_SLOTS` once M5 baseline exists.
"""

from __future__ import annotations

from eyenet.contracts.attribution import ProfileRow, RecipeResult

from ._base import get_slot_value, slots_present

NAME: str = "bot_or_automated_poster"
VERSION: str = "0.1"
REQUIRED_SLOTS: tuple[str, ...] = (
    "interaction_summary.conversation_initiation_rate",
    "lexical_summary.mattr",
)

# ---- UNCALIBRATED thresholds ------------------------------------------------
UNCALIBRATED_MIN_INITIATION_RATE: float = 0.95
"""Bot initiates ≥ 95% of its own messages (almost never replies)."""

UNCALIBRATED_MAX_MATTR: float = 0.65
"""Low lexical diversity; bots reuse vocabulary mechanically."""

UNCALIBRATED_MIN_OBSERVATION_COUNT: int = 30
"""At least N observations for reliable detection."""
# -----------------------------------------------------------------------------


def evaluate(profile: ProfileRow, derived_from_observation_count: int) -> RecipeResult:
    if not slots_present(profile, REQUIRED_SLOTS):
        return RecipeResult(
            matches=False,
            confidence=0.0,
            reasoning={"skip_reason": "required_slots_absent", "calibrated": False},
        )

    init_rate = get_slot_value(profile, "interaction_summary.conversation_initiation_rate")
    mattr = get_slot_value(profile, "lexical_summary.mattr")

    if not isinstance(init_rate, float | int) or not isinstance(mattr, float | int):
        return RecipeResult(
            matches=False,
            confidence=0.0,
            reasoning={"skip_reason": "slot_value_not_numeric", "calibrated": False},
        )

    init_rate = float(init_rate)
    mattr = float(mattr)

    high_init = init_rate >= UNCALIBRATED_MIN_INITIATION_RATE
    low_mattr = mattr <= UNCALIBRATED_MAX_MATTR
    matches = high_init and low_mattr

    count_confidence = min(1.0, derived_from_observation_count / UNCALIBRATED_MIN_OBSERVATION_COUNT)

    if matches:
        # Confidence grows with how far each signal is from the boundary.
        init_signal = (init_rate - UNCALIBRATED_MIN_INITIATION_RATE) / (
            1.0 - UNCALIBRATED_MIN_INITIATION_RATE
        )
        mattr_signal = (UNCALIBRATED_MAX_MATTR - mattr) / UNCALIBRATED_MAX_MATTR
        signal_confidence = (init_signal + mattr_signal) / 2.0
        confidence = round(count_confidence * signal_confidence, 4)
    else:
        confidence = 0.0

    return RecipeResult(
        matches=matches,
        confidence=confidence,
        reasoning={
            "calibrated": False,
            "init_rate_observed": round(init_rate, 6),
            "mattr_observed": round(mattr, 6),
            "threshold_min_initiation_rate": UNCALIBRATED_MIN_INITIATION_RATE,
            "threshold_max_mattr": UNCALIBRATED_MAX_MATTR,
            "observation_count": derived_from_observation_count,
            "note": "punctuation_style and typo_signature not yet included; see M5",
        },
    )


class BotOrAutomatedPosterRecipe:
    name = NAME
    version = VERSION
    required_slots = REQUIRED_SLOTS

    def evaluate(self, profile: ProfileRow, derived_from_observation_count: int) -> RecipeResult:
        return evaluate(profile, derived_from_observation_count)


__all__ = ["NAME", "VERSION", "BotOrAutomatedPosterRecipe"]
