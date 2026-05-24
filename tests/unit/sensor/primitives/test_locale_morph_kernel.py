"""Unit tests for the M6.5 _locale_morph_kernel + es ruleset + language gate.

The kernel test set is deliberately small: the kernel is a thin wrapper
that runs spaCy and accumulates counters; the load-bearing logic lives
in the ruleset rules and the per-primitive modules, which have their
own test files.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from eyenet.sensor.primitives import _locale_morph_kernel as kernel
from eyenet.sensor.primitives._locale_rules import RULESETS, get_ruleset, is_spanish
from eyenet.sensor.primitives._locale_rules._language_gate import detect_language
from eyenet.sensor.primitives._locale_rules.es import RULESET as ES_RULESET


def _corpus_bodies(texts: list[str]) -> tuple[list[tuple[datetime, UUID, str]], dict[str, str]]:
    corpus: list[tuple[datetime, UUID, str]] = []
    bodies: dict[str, str] = {}
    for i, text in enumerate(texts):
        ref = f"ref:{i}"
        corpus.append((datetime(2026, 5, 1, 12, i, tzinfo=UTC), uuid4(), ref))
        bodies[ref] = text
    return corpus, bodies


# ─── language gate ───────────────────────────────────────────────────────────


@pytest.mark.unit
def test_is_spanish_on_spanish_bag() -> None:
    assert is_spanish(["de", "la", "que", "el", "en", "y"]) is True


@pytest.mark.unit
def test_is_spanish_on_english_bag() -> None:
    assert is_spanish(["the", "of", "and", "to", "a", "in"]) is False


@pytest.mark.unit
def test_is_spanish_empty_bag() -> None:
    assert is_spanish([]) is False


@pytest.mark.unit
def test_detect_language_spanish() -> None:
    assert detect_language(["de", "la", "que", "el", "en"]) == "es"


@pytest.mark.unit
def test_detect_language_english() -> None:
    assert detect_language(["the", "of", "and", "to", "a", "in"]) == "en"


@pytest.mark.unit
def test_detect_language_empty_returns_none() -> None:
    assert detect_language([]) is None


@pytest.mark.unit
def test_detect_language_below_min_anchors_returns_none() -> None:
    # Only one anchor in either set — gate refuses to call it.
    assert detect_language(["the", "xyzzy", "qwert"]) is None


# ─── ruleset registry ────────────────────────────────────────────────────────


@pytest.mark.unit
def test_es_ruleset_registered() -> None:
    assert "es" in RULESETS
    assert get_ruleset("es") is ES_RULESET


@pytest.mark.unit
def test_unknown_language_returns_none() -> None:
    assert get_ruleset("xx") is None


# ─── kernel pass ─────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_kernel_empty_corpus_returns_none() -> None:
    assert kernel.compute_morph_analysis(corpus=[], bodies={}, ruleset=ES_RULESET) is None


@pytest.mark.unit
def test_kernel_all_bodies_missing_returns_none() -> None:
    corpus, _ = _corpus_bodies(["x"])
    # bodies dict empty — every evidence_ref misses
    assert kernel.compute_morph_analysis(corpus=corpus, bodies={}, ruleset=ES_RULESET) is None


@pytest.mark.unit
def test_kernel_accumulates_pos_bigrams_and_eval_hits() -> None:
    corpus, bodies = _corpus_bodies(
        [
            "Tengo una casita muy bonita en la playa.",
            "El perrito ladra mucho y la casucha es vieja.",
        ]
    )
    analysis = kernel.compute_morph_analysis(corpus=corpus, bodies=bodies, ruleset=ES_RULESET)
    assert analysis is not None
    assert analysis.total_tokens > 0
    assert len(analysis.pos_bigrams) > 0
    # casita + perrito = diminutive ≥ 2; casucha = pejorative ≥ 1
    assert analysis.evaluative_counts.get("diminutive", 0) >= 2
    assert analysis.evaluative_counts.get("pejorative", 0) >= 1


@pytest.mark.unit
def test_kernel_window_bounds_match_first_and_last_message() -> None:
    corpus, bodies = _corpus_bodies(["hola amigo", "como estas"])
    analysis = kernel.compute_morph_analysis(corpus=corpus, bodies=bodies, ruleset=ES_RULESET)
    assert analysis is not None
    assert analysis.window_start_ts == corpus[0][0].timestamp()
    assert analysis.window_end_ts == corpus[-1][0].timestamp()


# ─── es ruleset — direct rule checks ─────────────────────────────────────────


@pytest.mark.unit
def test_es_ruleset_language_attr() -> None:
    assert ES_RULESET.language == "es"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("text", "expected_bucket"),
    [
        ("casita", "diminutive"),
        ("perrito", "diminutive"),
        ("casucha", "pejorative"),
        ("golazo", "augmentative"),
    ],
)
def test_es_evaluative_classification(text: str, expected_bucket: str) -> None:
    """Round-trip through the kernel to verify spaCy POS-tagged classification."""
    sentence = f"Mira el {text} ahi."
    corpus, bodies = _corpus_bodies([sentence])
    analysis = kernel.compute_morph_analysis(corpus=corpus, bodies=bodies, ruleset=ES_RULESET)
    assert analysis is not None
    assert analysis.evaluative_counts.get(expected_bucket, 0) >= 1


@pytest.mark.unit
def test_es_blocklist_filters_bonito() -> None:
    """``bonito`` matches the diminutive regex but is lexicalized."""
    corpus, bodies = _corpus_bodies(["El perro es bonito y el gato tambien."])
    analysis = kernel.compute_morph_analysis(corpus=corpus, bodies=bodies, ruleset=ES_RULESET)
    assert analysis is not None
    assert analysis.evaluative_counts.get("diminutive", 0) == 0


@pytest.mark.unit
def test_es_detects_subjunctive() -> None:
    corpus, bodies = _corpus_bodies(
        ["Quiero que vengas mañana. Si tuviera tiempo te ayudaria. Ojala llueva."]
    )
    analysis = kernel.compute_morph_analysis(corpus=corpus, bodies=bodies, ruleset=ES_RULESET)
    assert analysis is not None
    assert analysis.optional_grammar_counts.get("subjunctive", 0) >= 1


@pytest.mark.unit
def test_es_detects_clitic_buckets() -> None:
    corpus, bodies = _corpus_bodies(
        ["Le dije que se fuera. La vi en el parque. Lo encontre dormido."]
    )
    analysis = kernel.compute_morph_analysis(corpus=corpus, bodies=bodies, ruleset=ES_RULESET)
    assert analysis is not None
    counts = analysis.optional_grammar_counts
    # at least one of each clitic bucket fired
    assert counts.get("clitic_le", 0) >= 1
    assert counts.get("clitic_la", 0) >= 1
    assert counts.get("clitic_lo", 0) >= 1


@pytest.mark.unit
def test_es_detects_compound_past() -> None:
    corpus, bodies = _corpus_bodies(
        ["He comido pizza esta tarde. Habiamos visto la pelicula antes."]
    )
    analysis = kernel.compute_morph_analysis(corpus=corpus, bodies=bodies, ruleset=ES_RULESET)
    assert analysis is not None
    assert analysis.optional_grammar_counts.get("compound_past", 0) >= 1


# ─── memo (single-pass per actor) ────────────────────────────────────────────


@pytest.mark.unit
def test_kernel_memoizes_within_same_corpus() -> None:
    """Three back-to-back calls with the same corpus → spaCy runs ONCE.

    Reproduces the production case: the sensor dispatches all three M6.5
    primitives back-to-back per actor with identical corpora; the memo
    must collapse them to a single tagger pass.
    """
    corpus, bodies = _corpus_bodies(
        [
            "Tengo una casita muy bonita. El perrito ladra mucho.",
            "Habiamos comido cuando le dije que se fuera de aqui.",
        ]
    )
    kernel._reset_cache_for_tests()
    baseline = kernel._stats.pipe_calls

    first = kernel.compute_morph_analysis(corpus=corpus, bodies=bodies, ruleset=ES_RULESET)
    second = kernel.compute_morph_analysis(corpus=corpus, bodies=bodies, ruleset=ES_RULESET)
    third = kernel.compute_morph_analysis(corpus=corpus, bodies=bodies, ruleset=ES_RULESET)

    assert first is not None
    assert second is first  # exact same MorphAnalysis instance (cache hit)
    assert third is first
    assert kernel._stats.pipe_calls - baseline == 1


@pytest.mark.unit
def test_kernel_cache_misses_when_evidence_refs_change() -> None:
    """A different ref tuple → fresh tagger pass."""
    corpus_a, bodies_a = _corpus_bodies(["Tengo una casita en la playa."])
    # Different texts AND different refs (via _corpus_bodies → fresh ref:0,1)
    corpus_b = [(corpus_a[0][0], corpus_a[0][1], "ref:DIFFERENT")]
    bodies_b = {"ref:DIFFERENT": "El perrito ladra muchisimo."}

    kernel._reset_cache_for_tests()
    baseline = kernel._stats.pipe_calls

    a = kernel.compute_morph_analysis(corpus=corpus_a, bodies=bodies_a, ruleset=ES_RULESET)
    b = kernel.compute_morph_analysis(corpus=corpus_b, bodies=bodies_b, ruleset=ES_RULESET)

    assert a is not None
    assert b is not None
    assert a is not b
    assert kernel._stats.pipe_calls - baseline == 2


@pytest.mark.unit
def test_kernel_cache_misses_on_same_refs_different_bodies() -> None:
    """Bodies fingerprint defends against same-refs-different-content collisions.

    If the cache keyed only on ``(language, refs)``, two callers passing
    the SAME corpus refs with DIFFERENT body content would receive the
    first caller's MorphAnalysis — a silent stale-result bug.
    """
    corpus, _ = _corpus_bodies(["placeholder"])  # one ref, content irrelevant
    refs = [r for _, _, r in corpus]
    bodies_a = {refs[0]: "Tengo una casita muy bonita en la playa."}
    bodies_b = {refs[0]: "El perrito ladra mucho y la casucha es vieja."}

    kernel._reset_cache_for_tests()
    baseline = kernel._stats.pipe_calls

    a = kernel.compute_morph_analysis(corpus=corpus, bodies=bodies_a, ruleset=ES_RULESET)
    b = kernel.compute_morph_analysis(corpus=corpus, bodies=bodies_b, ruleset=ES_RULESET)

    assert a is not None
    assert b is not None
    assert a is not b  # not the cached value
    # Two distinct kernel passes, not one.
    assert kernel._stats.pipe_calls - baseline == 2


@pytest.mark.unit
def test_kernel_cache_records_negative_result() -> None:
    """Empty-body corpus caches a ``None`` so the second call doesn't retry."""
    corpus, _ = _corpus_bodies(["x"])  # bodies built but we pass an empty bodies dict
    kernel._reset_cache_for_tests()
    baseline = kernel._stats.pipe_calls

    first = kernel.compute_morph_analysis(corpus=corpus, bodies={}, ruleset=ES_RULESET)
    second = kernel.compute_morph_analysis(corpus=corpus, bodies={}, ruleset=ES_RULESET)

    assert first is None
    assert second is None
    # Neither call should have invoked nlp.pipe — first short-circuits on
    # empty bodies, second hits the memo.
    assert kernel._stats.pipe_calls - baseline == 0


# ─── evidence_ref_for helper ─────────────────────────────────────────────────


@pytest.mark.unit
def test_evidence_ref_for_returns_last_in_bodies() -> None:
    corpus, bodies = _corpus_bodies(["a", "b", "c"])
    assert kernel.evidence_ref_for(corpus, bodies) == corpus[-1][2]


@pytest.mark.unit
def test_evidence_ref_for_skips_missing_trailing_body() -> None:
    corpus, bodies = _corpus_bodies(["a", "b", "c"])
    # Drop the trailing body — helper should fall back to the second-to-last.
    del bodies[corpus[-1][2]]
    assert kernel.evidence_ref_for(corpus, bodies) == corpus[-2][2]


@pytest.mark.unit
def test_evidence_ref_for_returns_none_when_no_overlap() -> None:
    corpus, _ = _corpus_bodies(["a", "b"])
    assert kernel.evidence_ref_for(corpus, {}) is None


# ─── auto-fetch (OSError → spacy.cli.download → retry) ───────────────────────


@pytest.mark.unit
def test_load_nlp_auto_downloads_on_missing_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """First spacy.load raises OSError → download fires → second load succeeds.

    The second load is allowed to hit the real cached model on disk —
    the test relies on ``es_core_news_sm`` being installed (it is, as a
    test dependency). Fully mocking the model would mean returning a
    plausible ``spacy.Language`` instance, which is more brittle than
    just letting the real load complete.
    """
    import spacy

    kernel._reset_for_tests()
    baseline_load_count = {"n": 0}
    download_count = {"n": 0}
    real_load = spacy.load

    def fake_load(name: str, **kwargs: object) -> object:
        baseline_load_count["n"] += 1
        if baseline_load_count["n"] == 1:
            raise OSError(f"simulated missing model {name!r}")
        return real_load(name, **kwargs)  # type: ignore[arg-type]

    def fake_download(name: str) -> None:
        download_count["n"] += 1
        # No-op: the real model is already cached in site-packages.

    monkeypatch.setattr("spacy.load", fake_load)
    monkeypatch.setattr(kernel, "_spacy_download", fake_download)

    nlp = kernel._load_nlp()

    assert baseline_load_count["n"] == 2  # first failed, second succeeded
    assert download_count["n"] == 1
    assert nlp is not None
    # Subsequent _load_nlp calls hit the singleton — no further spacy.load.
    kernel._load_nlp()
    assert baseline_load_count["n"] == 2

    # Leave a fresh model in the singleton for sibling tests (without the
    # monkeypatch, _load_nlp will lazy-reload the real model).
    kernel._reset_for_tests()
