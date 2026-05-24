"""Linker comparator registry.

REGISTRY is the ordered tuple of all active comparators. The Linker runs every
comparator in REGISTRY against every incoming ProfileCurrent. New comparators
(tfidf_cosine, mattr_l1, ...) drop in here without touching the Linker.

`select_for_slot(slot_path)` returns the comparator for a given profile slot path,
or None if no comparator targets that slot.
"""

from __future__ import annotations

from ._base import Comparator, ComparisonResult
from .char_ngram_simhash_hamming import CharNgramSimhashHamming
from .function_word_simhash_hamming import FunctionWordSimhashHamming
from .optional_grammar_simhash_hamming import OptionalGrammarSimhashHamming
from .pos_ngram_simhash_hamming import PosNgramSimhashHamming

REGISTRY: tuple[Comparator, ...] = (
    FunctionWordSimhashHamming,
    CharNgramSimhashHamming,
    PosNgramSimhashHamming,
    OptionalGrammarSimhashHamming,
)


def select_for_slot(slot_path: str) -> Comparator | None:
    for c in REGISTRY:
        if c.slot_path == slot_path:
            return c
    return None


__all__ = [
    "REGISTRY",
    "CharNgramSimhashHamming",
    "Comparator",
    "ComparisonResult",
    "FunctionWordSimhashHamming",
    "OptionalGrammarSimhashHamming",
    "PosNgramSimhashHamming",
    "select_for_slot",
]
