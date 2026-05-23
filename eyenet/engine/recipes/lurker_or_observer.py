"""Recipe: lurker_or_observer.

An actor who is present but rarely initiates conversation or contributes
original content. Two complementary patterns, OR-combined:

* Pattern A — passive responder: ``init_rate <= 0.20``.
  Catches the strict "replies-heavy" lurker class.
* Pattern B — long-tail occasional presence:
  ``msg_per_day <= 2.0 AND corpus_span_days >= 7.0``.
  Catches actors who appear rarely across a long span.

CALIBRATION (M5, 2026-05-22 against rutify-full-2026-05-02):

On the 74-actor labeled set the artifact records:
* Pattern A alone: TP=2, FP=0, P=1.000, R=0.40.
* Pattern A OR Pattern B: TP=5, FP=0, P=1.000, R=1.00.

Pattern B was calibrated alongside Pattern A in M5 but ``DEPLOYMENT-
BLOCKED`` because the temporal slots did not exist. M5.5 (BEHAVE-TEXT
0.1.2 meta.* primitives) populates ``temporal_summary.msg_per_day`` and
``temporal_summary.corpus_span_days``; Pattern B now ships.
"""

from __future__ import annotations

from eyenet.contracts.attribution import ProfileRow, RecipeResult

from ._base import get_slot_value, slots_present

NAME: str = "lurker_or_observer"
VERSION: str = "0.3"

# Pattern A and Pattern B require disjoint slot subsets, OR-combined.
# REQUIRED_SLOTS is empty because the registry's `pick_winner` gates on
# AND-of-all-required-slots; an OR-combinator recipe must run whenever
# EITHER pattern's slots are populated. The internal per-pattern guards
# below handle the "no data at all" case.
REQUIRED_SLOTS: tuple[str, ...] = ()

_PATTERN_A_SLOTS: tuple[str, ...] = ("interaction_summary.conversation_initiation_rate",)
_PATTERN_B_SLOTS: tuple[str, ...] = (
    "temporal_summary.msg_per_day",
    "temporal_summary.corpus_span_days",
)

# ---- Calibrated thresholds (M5 / Rutify 2026-05-22) -----------------------
MAX_INITIATION_RATE: float = 0.20
"""Pattern A: passive responder. Loosest value meeting precision >= 0.70
on the v0 single-axis recipe (P=1.000 R=0.400)."""

MAX_MSG_PER_DAY: float = 2.0
"""Pattern B: long-tail upper bound on daily message rate."""

MIN_CORPUS_SPAN_DAYS: float = 7.0
"""Pattern B: minimum wall-clock span (filters out brief activity bursts
that incidentally hit the msg_per_day threshold)."""

MIN_OBSERVATION_COUNT: int = 20
"""At least N observations required before the recipe fires confidently."""
# ---------------------------------------------------------------------------


def evaluate(profile: ProfileRow, derived_from_observation_count: int) -> RecipeResult:
    pattern_a_present = slots_present(profile, _PATTERN_A_SLOTS)
    pattern_b_present = slots_present(profile, _PATTERN_B_SLOTS)

    if not pattern_a_present and not pattern_b_present:
        return RecipeResult(
            matches=False,
            confidence=0.0,
            reasoning={"skip_reason": "required_slots_absent", "calibrated": True},
        )

    init_rate: float | None = None
    msg_per_day: float | None = None
    corpus_span_days: float | None = None

    pattern_a_matches = False
    pattern_a_signal = 0.0
    if pattern_a_present:
        raw_init = get_slot_value(profile, "interaction_summary.conversation_initiation_rate")
        if isinstance(raw_init, float | int) and not isinstance(raw_init, bool):
            init_rate = float(raw_init)
            pattern_a_matches = init_rate <= MAX_INITIATION_RATE
            if pattern_a_matches and MAX_INITIATION_RATE > 0.0:
                pattern_a_signal = 1.0 - (init_rate / MAX_INITIATION_RATE)

    pattern_b_matches = False
    pattern_b_signal = 0.0
    if pattern_b_present:
        raw_mpd = get_slot_value(profile, "temporal_summary.msg_per_day")
        raw_span = get_slot_value(profile, "temporal_summary.corpus_span_days")
        if (
            isinstance(raw_mpd, float | int)
            and not isinstance(raw_mpd, bool)
            and isinstance(raw_span, float | int)
            and not isinstance(raw_span, bool)
        ):
            msg_per_day = float(raw_mpd)
            corpus_span_days = float(raw_span)
            pattern_b_matches = (
                msg_per_day <= MAX_MSG_PER_DAY and corpus_span_days >= MIN_CORPUS_SPAN_DAYS
            )
            if pattern_b_matches and MAX_MSG_PER_DAY > 0.0:
                # Signal strength = how far below the rate ceiling, saturates at 0 mpd.
                pattern_b_signal = 1.0 - (msg_per_day / MAX_MSG_PER_DAY)

    matches = pattern_a_matches or pattern_b_matches
    signal_confidence = max(pattern_a_signal, pattern_b_signal)
    count_confidence = min(1.0, derived_from_observation_count / MIN_OBSERVATION_COUNT)
    confidence = round(count_confidence * signal_confidence, 4) if matches else 0.0

    matched_patterns: list[str] = []
    if pattern_a_matches:
        matched_patterns.append("A")
    if pattern_b_matches:
        matched_patterns.append("B")

    reasoning: dict[str, object] = {
        "calibrated": True,
        "calibration_corpus": "rutify-full-2026-05-02",
        "matched_patterns": matched_patterns,
        "threshold_max_initiation_rate": MAX_INITIATION_RATE,
        "threshold_max_msg_per_day": MAX_MSG_PER_DAY,
        "threshold_min_corpus_span_days": MIN_CORPUS_SPAN_DAYS,
        "observation_count": derived_from_observation_count,
    }
    if init_rate is not None:
        reasoning["init_rate_observed"] = round(init_rate, 6)
    if msg_per_day is not None:
        reasoning["msg_per_day_observed"] = round(msg_per_day, 6)
    if corpus_span_days is not None:
        reasoning["corpus_span_days_observed"] = round(corpus_span_days, 6)

    return RecipeResult(matches=matches, confidence=confidence, reasoning=reasoning)


class LurkerOrObserverRecipe:
    name = NAME
    version = VERSION
    required_slots = REQUIRED_SLOTS

    def evaluate(self, profile: ProfileRow, derived_from_observation_count: int) -> RecipeResult:
        return evaluate(profile, derived_from_observation_count)


__all__ = [
    "MAX_INITIATION_RATE",
    "MAX_MSG_PER_DAY",
    "MIN_CORPUS_SPAN_DAYS",
    "MIN_OBSERVATION_COUNT",
    "NAME",
    "VERSION",
    "LurkerOrObserverRecipe",
]
