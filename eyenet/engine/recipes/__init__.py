"""Recipe registry — all active role recipes.

Engine calls `pick_winner(profile, observation_count)` after each slot update.
Add new recipes here as they land; no other file needs to change.
"""

from __future__ import annotations

from eyenet.contracts.attribution import ProfileRow, RecipeResult, RoleSignal

from ._base import Recipe, slots_present
from .bot_or_automated_poster import BotOrAutomatedPosterRecipe
from .chatty_member import ChattyMemberRecipe
from .lurker_or_observer import LurkerOrObserverRecipe

REGISTRY: tuple[Recipe, ...] = (  # type: ignore[assignment]
    LurkerOrObserverRecipe(),
    BotOrAutomatedPosterRecipe(),
    ChattyMemberRecipe(),
)


def pick_winner(
    profile: ProfileRow,
    derived_from_observation_count: int,
) -> tuple[RoleSignal, float] | None:
    """Run all eligible recipes; return (role_signal, confidence) of the best match.

    A recipe is eligible when all its `required_slots` are present in the
    profile. Among eligible recipes that `matches=True`, the highest confidence
    wins. Ties are broken by registry order (stable).

    Returns None when no recipe matches or no recipe is eligible.
    """
    best_signal: RoleSignal | None = None
    best_confidence: float = 0.0

    for recipe in REGISTRY:
        if not slots_present(profile, recipe.required_slots):
            continue
        result: RecipeResult = recipe.evaluate(profile, derived_from_observation_count)
        if result.matches and result.confidence > best_confidence:
            best_signal = recipe.name
            best_confidence = result.confidence

    if best_signal is None:
        return None
    return best_signal, best_confidence


__all__ = ["REGISTRY", "Recipe", "pick_winner"]
