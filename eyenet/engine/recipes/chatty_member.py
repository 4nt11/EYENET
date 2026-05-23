"""Recipe: chatty_member.

A highly active community participant: large total message volume,
balanced between thread initiation and reply. Distinct from
``bot_or_automated_poster`` (which gates on tight content templating) and
``lurker_or_observer`` (which gates on low initiation rate).

CALIBRATION (M5 / Rutify 2026-05-22):

* Single-axis: ``msg_count >= 195``.
* On the 74-actor labeled set: TP=21, FP=0, FN=1, P=1.000, R=0.955,
  F1=0.977. The single FN is a borderline actor labeled chatty_member at
  confidence=medium with msg_count=128 — a labeler edge case, not a
  recipe failure.

The required slot ``temporal_summary.message_count`` is populated by the
``meta.total_messages`` BEHAVE-TEXT 0.1.2 primitive (wired in M5.5).
"""

from __future__ import annotations

from eyenet.contracts.attribution import ProfileRow, RecipeResult

from ._base import get_slot_value, slots_present

NAME: str = "chatty_member"
VERSION: str = "0.1"
REQUIRED_SLOTS: tuple[str, ...] = ("temporal_summary.message_count",)

# ---- Calibrated thresholds (M5 / Rutify 2026-05-22) -----------------------
MIN_MESSAGE_COUNT: int = 195
"""Calibrated against the Rutify labeled set (74 actors). Loosest msg_count
threshold meeting precision >= 0.70; empirically achieved P=1.000 R=0.955."""

MIN_OBSERVATION_COUNT: int = 20
"""Floor below which confidence is dampened."""
# ---------------------------------------------------------------------------


def evaluate(profile: ProfileRow, derived_from_observation_count: int) -> RecipeResult:
    if not slots_present(profile, REQUIRED_SLOTS):
        return RecipeResult(
            matches=False,
            confidence=0.0,
            reasoning={
                "skip_reason": "required_slots_absent",
                "calibrated": True,
            },
        )

    msg_count = get_slot_value(profile, "temporal_summary.message_count")
    if not isinstance(msg_count, int | float):
        return RecipeResult(
            matches=False,
            confidence=0.0,
            reasoning={"skip_reason": "message_count_not_numeric", "calibrated": True},
        )

    msg_count_int = int(msg_count)
    matches = msg_count_int >= MIN_MESSAGE_COUNT

    count_confidence = min(1.0, derived_from_observation_count / MIN_OBSERVATION_COUNT)
    if matches:
        # Signal grows with how far above the threshold (saturating at 5x).
        signal_confidence = min(1.0, msg_count_int / (MIN_MESSAGE_COUNT * 5))
        confidence = round(count_confidence * signal_confidence, 4)
    else:
        confidence = 0.0

    return RecipeResult(
        matches=matches,
        confidence=confidence,
        reasoning={
            "calibrated": True,
            "calibration_corpus": "rutify-full-2026-05-02",
            "msg_count_observed": msg_count_int,
            "threshold_min_message_count": MIN_MESSAGE_COUNT,
            "observation_count": derived_from_observation_count,
        },
    )


class ChattyMemberRecipe:
    name = NAME
    version = VERSION
    required_slots = REQUIRED_SLOTS

    def evaluate(self, profile: ProfileRow, derived_from_observation_count: int) -> RecipeResult:
        return evaluate(profile, derived_from_observation_count)


__all__ = [
    "MIN_MESSAGE_COUNT",
    "MIN_OBSERVATION_COUNT",
    "NAME",
    "VERSION",
    "ChattyMemberRecipe",
]
