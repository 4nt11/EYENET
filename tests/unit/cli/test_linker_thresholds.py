"""Per-language threshold resolution on LinkerThresholds (PLAN §M5)."""

from __future__ import annotations

import pytest

from eyenet.cli.config import LinkerThresholds


@pytest.mark.unit
def test_default_language_blind_for_comparator() -> None:
    t = LinkerThresholds(function_word_simhash_hamming=8, char_ngram_simhash_hamming=10)
    assert t.for_comparator("function_word_simhash_hamming") == 8
    assert t.for_comparator("char_ngram_simhash_hamming") == 10


@pytest.mark.unit
def test_per_language_override_wins_when_present() -> None:
    t = LinkerThresholds(
        function_word_simhash_hamming=8,
        function_word_simhash_hamming_per_lang={"es": 14},
    )
    assert t.for_comparator("function_word_simhash_hamming", "es") == 14


@pytest.mark.unit
def test_per_language_unknown_lang_falls_back_to_default() -> None:
    t = LinkerThresholds(
        function_word_simhash_hamming=8,
        function_word_simhash_hamming_per_lang={"es": 14},
    )
    # "fr" is not in the override dict — fall back to language-blind default.
    assert t.for_comparator("function_word_simhash_hamming", "fr") == 8


@pytest.mark.unit
def test_per_language_none_argument_uses_default() -> None:
    t = LinkerThresholds(
        function_word_simhash_hamming=8,
        function_word_simhash_hamming_per_lang={"es": 14},
    )
    assert t.for_comparator("function_word_simhash_hamming", None) == 8


@pytest.mark.unit
def test_per_language_empty_dict_uses_default() -> None:
    # Explicit empty per-lang dict overrides the calibrated factory default.
    t = LinkerThresholds(
        function_word_simhash_hamming=8,
        function_word_simhash_hamming_per_lang={},
    )
    assert t.for_comparator("function_word_simhash_hamming", "es") == 8


@pytest.mark.unit
def test_factory_default_disables_simhash_for_spanish() -> None:
    """M5 / Rutify calibration: simhash comparators ship disabled for es."""
    t = LinkerThresholds()
    assert t.for_comparator("function_word_simhash_hamming", "es") is None
    assert t.for_comparator("char_ngram_simhash_hamming", "es") is None
    # Other languages still use the language-blind default.
    assert t.for_comparator("function_word_simhash_hamming", "en") == 8
    assert t.for_comparator("char_ngram_simhash_hamming", "en") == 10


@pytest.mark.unit
def test_unknown_comparator_returns_legacy_fallback() -> None:
    t = LinkerThresholds()
    # Legacy behavior preserved: unknown comparator name returns 8.
    assert t.for_comparator("nonexistent_comparator") == 8


@pytest.mark.unit
def test_per_language_none_means_disabled() -> None:
    """None in per_lang dict = explicit disable; for_comparator returns None."""
    t = LinkerThresholds(
        function_word_simhash_hamming=8,
        function_word_simhash_hamming_per_lang={"es": None},
    )
    assert t.for_comparator("function_word_simhash_hamming", "es") is None


@pytest.mark.unit
def test_per_language_disable_does_not_affect_other_langs() -> None:
    t = LinkerThresholds(
        char_ngram_simhash_hamming=10,
        char_ngram_simhash_hamming_per_lang={"es": None, "fr": 12},
    )
    assert t.for_comparator("char_ngram_simhash_hamming", "es") is None
    assert t.for_comparator("char_ngram_simhash_hamming", "fr") == 12
    # Language not in dict — falls back to language-blind default.
    assert t.for_comparator("char_ngram_simhash_hamming", "en") == 10


@pytest.mark.unit
def test_per_language_disable_with_no_language_argument_uses_default() -> None:
    """If the slot has no detected language, the disable sentinel doesn't apply."""
    t = LinkerThresholds(
        function_word_simhash_hamming=8,
        function_word_simhash_hamming_per_lang={"es": None},
    )
    assert t.for_comparator("function_word_simhash_hamming", None) == 8
