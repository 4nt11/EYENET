"""Shared language gate for locale-aware primitives.

Function-word overlap vote between Spanish and English anchor sets. The
anchor sets are the highest-frequency function words for each language,
deliberately small (~16 tokens each); the gate is a pre-filter, not a
classifier. Genuine language identification is the job of
``lexical.dialect_region`` and downstream consumers.

Two callers with intentionally-different thresholds — DO NOT consolidate
into one function:

* :func:`is_spanish` — loose binary. Ties → True. Used by
  ``dialect_region`` (M6): if a corpus is Spanish-shaped at all, run the
  regional-marker detector and let it argue ``unknown`` vs. a region
  code. Permissive on purpose; the downstream margin gate inside
  ``dialect_region`` handles ambiguous cases.

* :func:`detect_language` — strict 3-way classifier. Requires ≥2 anchor
  hits on the winning side, returns ``None`` when ambiguous. Used by
  the M6.5 spaCy trio (``pos_ngram_signature``,
  ``evaluative_morphology_density``, ``optional_grammar_signature``):
  those primitives must skip emission rather than fall through with
  bad language signal — wrong-language input would produce noise
  hashes that pollute the linker's Hamming space.

If you find yourself reaching for one and getting wrong-looking
behaviour, you probably want the other. They are NOT bugs of each
other.
"""

from __future__ import annotations

_MIN_ANCHOR_HITS: int = 2

_ES_GATE: frozenset[str] = frozenset(
    {
        "de",
        "la",
        "que",
        "el",
        "en",
        "y",
        "a",
        "los",
        "del",
        "se",
        "las",
        "un",
        "por",
        "con",
        "una",
        "su",
        "para",
    }
)
_EN_GATE: frozenset[str] = frozenset(
    {
        "the",
        "of",
        "and",
        "to",
        "a",
        "in",
        "is",
        "it",
        "you",
        "that",
        "he",
        "was",
        "for",
        "on",
        "are",
        "with",
        "as",
    }
)


def is_spanish(token_bag: list[str]) -> bool:
    """Return True when the token bag looks like Spanish (not English).

    Empty bags return False so callers consistently treat "no signal" as
    "skip." Ties resolve to Spanish — the only locale ruleset shipped in
    M6.5; non-Spanish callers must use a stricter classifier downstream.
    """
    if not token_bag:
        return False
    token_set = set(token_bag)
    es_score = len(token_set & _ES_GATE)
    en_score = len(token_set & _EN_GATE)
    return es_score >= en_score


def detect_language(token_bag: list[str]) -> str | None:
    """Return a BCP-47 language code when the gate is confident.

    Returns ``"es"`` when Spanish wins, ``"en"`` when English wins by a
    clear margin (≥2 anchors), and ``None`` otherwise. This is the
    forward-looking shape for multi-language rulesets — even though only
    Spanish ships in M6.5, callers should ask for the language code, not
    a yes/no on Spanish.
    """
    if not token_bag:
        return None
    token_set = set(token_bag)
    es_score = len(token_set & _ES_GATE)
    en_score = len(token_set & _EN_GATE)
    if es_score == 0 and en_score == 0:
        return None
    if es_score >= en_score and es_score >= _MIN_ANCHOR_HITS:
        return "es"
    if en_score > es_score and en_score >= _MIN_ANCHOR_HITS:
        return "en"
    return None


__all__ = ["detect_language", "is_spanish"]
