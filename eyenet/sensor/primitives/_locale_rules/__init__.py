"""LocaleRuleset protocol + registry for the spaCy trio (M6.5).

Each language ships a single ruleset module (``es.py``, future ``en.py``,
``pt.py``, …) exposing a ``RULESET`` constant that implements
:class:`LocaleRuleset`. The kernel (``_locale_morph_kernel.py``) selects
a ruleset by language code and uses its classifier hooks on each token.

Adding a new language is purely additive: a new module + an entry in the
``RULESETS`` dict here. No primitive contract changes, no kernel
changes. The protocol is the seam.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from spacy.tokens import Doc, Token

from . import es
from ._language_gate import detect_language, is_spanish


@runtime_checkable
class LocaleRuleset(Protocol):
    """A per-language rule pack used by the morpho-syntactic kernel."""

    language: str

    def classify_evaluative(self, token: Token) -> str | None:
        """Return the evaluative bucket for this token, or None.

        Buckets are: ``"diminutive"``, ``"augmentative"``,
        ``"pejorative"``, ``"intensive"``. Tokens that do not carry any
        evaluative morphology return ``None``.
        """
        ...

    def classify_optional_grammar(
        self,
        token: Token,
        doc: Doc,
    ) -> str | None:
        """Return the optional-grammar choice point for this token, or None.

        Choice points are stylistic: compound past auxiliaries, subjunctive
        verb forms, clitic pronoun bucket (le/la/lo/les/las/los), and
        relative pronoun choice (que/cual/quien). Tokens outside these
        choice points return ``None``.
        """
        ...


RULESETS: dict[str, LocaleRuleset] = {"es": es.RULESET}


def get_ruleset(language: str) -> LocaleRuleset | None:
    """Return the ruleset for a BCP-47 language code, or None if unsupported."""
    return RULESETS.get(language)


__all__ = [
    "RULESETS",
    "LocaleRuleset",
    "detect_language",
    "get_ruleset",
    "is_spanish",
]
