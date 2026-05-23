"""Recipe protocol — every role recipe implements this interface.

A recipe is a pure function: given a profile snapshot + observation count,
decide whether the actor matches a role class. Recipes are evaluated by the
Engine after every slot update; the highest-confidence match wins.

`required_slots` lets the engine skip recipes whose inputs haven't arrived
yet (e.g. skip `bot_or_automated_poster` if `interaction_summary` is empty).
A dot-path like `"interaction_summary.conversation_initiation_rate"` means
`profile.interaction_summary.get("conversation_initiation_rate")` must be
non-None.

Thresholds in concrete recipes are `UNCALIBRATED_*` module constants until
the Rutify corpus grid lands (M5). The `reasoning` dict MUST carry
`"calibrated": False` while any threshold is uncalibrated.
"""

from __future__ import annotations

from typing import Protocol

from eyenet.contracts.attribution import ProfileRow, RecipeResult, RoleSignal


class Recipe(Protocol):
    name: RoleSignal
    version: str
    required_slots: tuple[str, ...]

    def evaluate(self, profile: ProfileRow, derived_from_observation_count: int) -> RecipeResult:
        """Evaluate the recipe against a profile snapshot.

        Args:
            profile: The current profile row (summaries are dicts of slot
                     dicts, each carrying ``value``, ``last_observation_id``,
                     ``derived_from_observation_count``).
            derived_from_observation_count: Top-level observation count from
                     the engine, passed separately so recipes don't need to
                     re-derive it from the summary blocks.

        Returns:
            RecipeResult with ``matches``, ``confidence``, and ``reasoning``.
            Reasoning must include ``"calibrated": False`` while thresholds
            are uncalibrated.
        """
        ...


def slots_present(profile: ProfileRow, required_slots: tuple[str, ...]) -> bool:
    """Return True if all required slot paths are populated in the profile."""
    for slot_path in required_slots:
        block_name, _, slot_key = slot_path.partition(".")
        block: dict[str, object] = getattr(profile, block_name, {})
        if not isinstance(block, dict) or slot_key not in block:
            return False
        slot_value = block[slot_key]
        if not isinstance(slot_value, dict) or slot_value.get("value") is None:
            return False
    return True


def get_slot_value(profile: ProfileRow, slot_path: str) -> object:
    """Extract a slot value from a profile using a dot-path.

    Returns None if the path is absent or the value is None.
    """
    block_name, _, slot_key = slot_path.partition(".")
    block = getattr(profile, block_name, None)
    if not isinstance(block, dict):
        return None
    slot = block.get(slot_key)
    if not isinstance(slot, dict):
        return None
    return slot.get("value")


__all__ = ["Recipe", "RecipeResult", "get_slot_value", "slots_present"]
