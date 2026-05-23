"""Recipe: lurker_or_observer.

An actor who is present but rarely initiates conversation or contributes
original content. Key signals: near-zero conversation initiation rate and
low message volume relative to time in corpus.

THRESHOLDS: all values are UNCALIBRATED. Rutify corpus grid (M5) will
replace these with empirically derived values. Reason dict carries
`"calibrated": False` on every evaluation until then.
"""

from __future__ import annotations

from eyenet.contracts.attribution import ProfileRow, RecipeResult

from ._base import get_slot_value, slots_present

NAME: str = "lurker_or_observer"
VERSION: str = "0.1"
REQUIRED_SLOTS: tuple[str, ...] = ("interaction_summary.conversation_initiation_rate",)

# ---- UNCALIBRATED thresholds ------------------------------------------------
UNCALIBRATED_MAX_INITIATION_RATE: float = 0.05
"""Actor initiates fewer than 5% of their own messages as thread-starters."""

UNCALIBRATED_MIN_OBSERVATION_COUNT: int = 20
"""At least N observations required before the recipe fires confidently."""
# -----------------------------------------------------------------------------


def evaluate(profile: ProfileRow, derived_from_observation_count: int) -> RecipeResult:
    if not slots_present(profile, REQUIRED_SLOTS):
        return RecipeResult(
            matches=False,
            confidence=0.0,
            reasoning={"skip_reason": "required_slots_absent", "calibrated": False},
        )

    init_rate = get_slot_value(profile, "interaction_summary.conversation_initiation_rate")
    if not isinstance(init_rate, float | int):
        return RecipeResult(
            matches=False,
            confidence=0.0,
            reasoning={"skip_reason": "init_rate_not_numeric", "calibrated": False},
        )

    init_rate = float(init_rate)
    matches = init_rate <= UNCALIBRATED_MAX_INITIATION_RATE

    # Confidence scales with observation count, capped at 1.0.
    count_confidence = min(1.0, derived_from_observation_count / UNCALIBRATED_MIN_OBSERVATION_COUNT)
    # Confidence also scales inversely with how close the value is to the threshold.
    signal_confidence = (1.0 - (init_rate / UNCALIBRATED_MAX_INITIATION_RATE)) if matches else 0.0
    confidence = round(count_confidence * signal_confidence, 4) if matches else 0.0

    return RecipeResult(
        matches=matches,
        confidence=confidence,
        reasoning={
            "calibrated": False,
            "init_rate_observed": round(init_rate, 6),
            "threshold_max_initiation_rate": UNCALIBRATED_MAX_INITIATION_RATE,
            "observation_count": derived_from_observation_count,
        },
    )


class LurkerOrObserverRecipe:
    name = NAME
    version = VERSION
    required_slots = REQUIRED_SLOTS

    def evaluate(self, profile: ProfileRow, derived_from_observation_count: int) -> RecipeResult:
        return evaluate(profile, derived_from_observation_count)


__all__ = ["NAME", "VERSION", "LurkerOrObserverRecipe"]
