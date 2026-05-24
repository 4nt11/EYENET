"""Shared kernel for the M6.5 spaCy trio.

The three locale-aware primitives —
:mod:`eyenet.sensor.primitives.pos_ngram_signature`,
:mod:`eyenet.sensor.primitives.evaluative_morphology_density`, and
:mod:`eyenet.sensor.primitives.optional_grammar_signature` — all derive
their values from a single morpho-syntactic pass over the per-actor
corpus. This module runs spaCy once per ``compute_morph_analysis`` call
and returns a frozen :class:`MorphAnalysis` dataclass; each primitive
then projects the relevant fields into an
:class:`behave_text.spec.Observation`.

spaCy model handling
====================

The model name (``es_core_news_sm``, ~13MB) is a module-level constant.
On first use the kernel lazy-loads it via :func:`spacy.load`. If the
model is not yet installed, it triggers
:func:`spacy.cli.download.download` automatically and retries the load.
This is the M6.5 operator decision (2026-05-23): EYENET ships small-
operator CTI, operators accept the storage cost in exchange for a tool
that works out of the box rather than one that needs a pre-flight
``python -m spacy download …`` step.

The downloaded model is cached at the spaCy-default location
(``site-packages``); subsequent runs in the same venv skip the network
round-trip. The kernel logs a structlog event
``event=spacy.model_downloaded`` so the one-shot fetch is operator-
visible in the audit trail / journald.

The model loads with ``parser`` and ``ner`` disabled. We only need the
tagger and morphologizer; disabling the parser cuts per-message cost by
~2x and is what makes the kernel cheap enough to ship in the default
sensor pipeline.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

import spacy
import structlog
from spacy.cli.download import download as _spacy_download
from spacy.language import Language

from ._locale_rules import LocaleRuleset

MODEL_NAME: str = "es_core_news_sm"
KERNEL_VERSION_TAG: str = "locale-morph-v1"
"""Source-label suffix shared by all three M6.5 primitives. Bumping this
tag invalidates downstream caches and signals operators that the kernel
behaviour has changed (rule changes in ``_locale_rules/*`` should bump
their own per-language tag instead — the kernel tag is for kernel-level
changes only)."""

# spaCy pipeline components we do NOT need for the trio. We disable parser
# (per-message cost) and NER (we don't care about named entities here);
# lemmatizer and attribute_ruler stay ENABLED — the optional-grammar
# rule pack reads ``token.lemma_`` for ``haber`` (compound past), and
# without lemmatizer that field is the empty string and the rule never
# fires. Empirically this re-enable costs ~30% load time on first call;
# the alternative is silently broken compound-past detection.
_DISABLED_PIPES: tuple[str, ...] = ("parser", "ner")

_BATCH_SIZE: int = 64
"""``nlp.pipe`` batch size. 64 is a reasonable balance between
throughput and memory; spaCy's internal default is 1000 which is too
hot for per-actor corpora of a few hundred messages."""

_log = structlog.get_logger(__name__)

_NLP: Language | None = None


def _load_nlp() -> Language:
    """Lazy singleton: load (or download then load) the Spanish model.

    First call in the process attempts ``spacy.load(MODEL_NAME)``. If the
    model is not installed (``OSError``), runs ``spacy.cli.download`` and
    retries exactly once. The loaded ``Language`` is cached at module
    scope; subsequent calls return the cached instance.
    """
    global _NLP  # noqa: PLW0603 — classic lazy-singleton pattern
    if _NLP is not None:
        return _NLP

    try:
        _NLP = spacy.load(MODEL_NAME, disable=list(_DISABLED_PIPES))
    except OSError:
        _log.warning(
            "spacy.model_downloading",
            model=MODEL_NAME,
            reason="missing_on_disk",
            note="auto-fetch per M6.5 operator decision; first-run only",
        )
        _spacy_download(MODEL_NAME)
        _NLP = spacy.load(MODEL_NAME, disable=list(_DISABLED_PIPES))
        _log.info("spacy.model_downloaded", model=MODEL_NAME)

    return _NLP


@dataclass(frozen=True)
class MorphAnalysis:
    """Derived morpho-syntactic statistics for one actor's corpus pass.

    All fields are accumulated over the entire corpus the kernel was
    handed; the M6.5 primitives set ``requires_full_corpus=True`` so the
    sensor passes the actor's full history.

    ``pos_bigrams`` keys are ``(prev_pos, curr_pos)`` UPOS pairs across
    each message; sentence boundaries are *not* breaks (the kernel does
    not run sentence segmentation — that would require the parser).
    Document boundaries (between messages) ARE breaks: a bigram never
    crosses two messages.

    ``window_start_ts`` / ``window_end_ts`` are the first and last
    timestamps from the corpus, surfaced so each primitive can build its
    :class:`behave_text.spec.Window` without re-walking the corpus list.
    """

    pos_bigrams: Counter[tuple[str, str]] = field(default_factory=Counter)
    evaluative_counts: dict[str, int] = field(default_factory=dict)
    optional_grammar_counts: dict[str, int] = field(default_factory=dict)
    total_tokens: int = 0
    total_evaluative_target_tokens: int = 0
    """Count of NOUN/ADJ tokens — denominator for evaluative morphology
    density. Using all-tokens as denominator under-weights actors with
    verb-heavy corpora; using only-target-tokens keeps the metric on a
    consistent scale across actors with different POS mixes."""

    window_start_ts: float = 0.0
    window_end_ts: float = 0.0


# POS categories that anchor the evaluative-target denominator.
_EVAL_DENOM_POS: frozenset[str] = frozenset({"NOUN", "ADJ"})


# Single-entry memo. The sensor's per-actor dispatch (``stylometric.py``)
# calls each of the three M6.5 primitives back-to-back with the SAME
# corpus and bodies; without a memo, the spaCy tagger pass runs three
# times per actor instead of once. We can't key on ``id(corpus)`` because
# the sensor builds a fresh list per primitive call — we need a
# deterministic key, so we hash on a tuple that includes the language,
# the evidence_ref tuple, AND a fingerprint of the bodies we'll actually
# process. The bodies fingerprint defends against callers that pass the
# same refs with different content (test contamination, future refactors
# that reuse refs across actors). Cache is single-slot — next actor's
# first call overwrites it, so it never grows unbounded.
_CacheKey = tuple[str, tuple[str, ...], int]
_CACHE_KEY: _CacheKey | None = None
_CACHE_VALUE: MorphAnalysis | None = None


@dataclass
class _KernelStats:
    """Test-visible counters. Production code does not read these.

    The leading underscore on the module-level ``_stats`` instance is
    the contract: it exists for unit/integration tests to assert
    properties like "the kernel ran spaCy exactly once for these three
    primitive calls." ``_reset_cache_for_tests`` zeroes the counters
    alongside the cache.
    """

    pipe_calls: int = 0
    cache_hits: int = 0
    cache_misses: int = 0


_stats = _KernelStats()


def _build_cache_key(
    corpus: list[tuple[datetime, UUID, str]],
    bodies: dict[str, str],
    ruleset: LocaleRuleset,
) -> _CacheKey:
    refs = tuple(ref for _, _, ref in corpus)
    # Hash only the bodies we'd actually feed to the tagger. Missing-ref
    # bodies become the empty string — equivalent input → equivalent key.
    body_sig = hash(tuple(bodies.get(ref, "") for ref in refs))
    return (ruleset.language, refs, body_sig)


def compute_morph_analysis(
    *,
    corpus: list[tuple[datetime, UUID, str]],
    bodies: dict[str, str],
    ruleset: LocaleRuleset,
) -> MorphAnalysis | None:
    """Run the tagger over the corpus and accumulate per-primitive stats.

    Returns ``None`` when the corpus has no message bodies in ``bodies``
    (every body fetch missed) — no Observation should be emitted by any
    primitive in that case.

    Bodies are looked up by evidence_ref; missing refs are silently
    skipped (collector / message-store ordering can lag behind the
    corpus cursor). Empty bodies are treated as if missing.

    Calls with identical ``(language, evidence_refs, bodies fingerprint)``
    hit the single-slot memo and skip the spaCy pass.
    """
    global _CACHE_KEY, _CACHE_VALUE  # noqa: PLW0603 — single-slot memo

    cache_key = _build_cache_key(corpus, bodies, ruleset)
    if cache_key == _CACHE_KEY:
        _stats.cache_hits += 1
        return _CACHE_VALUE
    _stats.cache_misses += 1

    bodies_list: list[str] = []
    ts_vals: list[float] = []
    for ts, _, evidence_ref in corpus:
        body = bodies.get(evidence_ref)
        if body:
            bodies_list.append(body)
            ts_vals.append(ts.timestamp())

    if not bodies_list:
        _CACHE_KEY = cache_key
        _CACHE_VALUE = None
        return None

    nlp = _load_nlp()
    _stats.pipe_calls += 1

    pos_bigrams: Counter[tuple[str, str]] = Counter()
    evaluative_counts: Counter[str] = Counter()
    optional_grammar_counts: Counter[str] = Counter()
    total_tokens = 0
    total_target_tokens = 0

    for doc in nlp.pipe(bodies_list, batch_size=_BATCH_SIZE):
        prev_pos: str | None = None
        for token in doc:
            if token.is_space:
                continue
            total_tokens += 1
            pos = token.pos_
            if prev_pos is not None:
                pos_bigrams[(prev_pos, pos)] += 1
            prev_pos = pos

            if pos in _EVAL_DENOM_POS:
                total_target_tokens += 1

            bucket = ruleset.classify_evaluative(token)
            if bucket is not None:
                evaluative_counts[bucket] += 1

            grammar_bucket = ruleset.classify_optional_grammar(token, doc)
            if grammar_bucket is not None:
                optional_grammar_counts[grammar_bucket] += 1

    result = MorphAnalysis(
        pos_bigrams=pos_bigrams,
        evaluative_counts=dict(evaluative_counts),
        optional_grammar_counts=dict(optional_grammar_counts),
        total_tokens=total_tokens,
        total_evaluative_target_tokens=total_target_tokens,
        window_start_ts=min(ts_vals),
        window_end_ts=max(ts_vals),
    )
    _CACHE_KEY = cache_key
    _CACHE_VALUE = result
    return result


def evidence_ref_for(
    corpus: list[tuple[datetime, UUID, str]],
    bodies: dict[str, str],
) -> str | None:
    """Return the last evidence_ref in ``corpus`` that's also in ``bodies``.

    The kernel filters out refs missing from ``bodies`` before computing,
    so stamping ``corpus[-1][2]`` blindly on an Observation can produce a
    reference the kernel never saw (the trailing message had a missing
    body). This helper walks the corpus in reverse and returns the most
    recent ref the kernel would have actually processed. Returns ``None``
    when no refs in the corpus have bodies — caller behaviour is to omit
    the field.
    """
    for _, _, ref in reversed(corpus):
        if ref in bodies:
            return ref
    return None


def _reset_cache_for_tests() -> None:
    """Drop the kernel's single-slot memo + reset stats counters.

    Leaves the loaded ``_NLP`` singleton in place — reloading spaCy
    between tests would multiply test-suite runtime by orders of
    magnitude. Use this in autouse fixtures to isolate cache state.
    """
    global _CACHE_KEY, _CACHE_VALUE  # noqa: PLW0603
    _CACHE_KEY = None
    _CACHE_VALUE = None
    _stats.pipe_calls = 0
    _stats.cache_hits = 0
    _stats.cache_misses = 0


def _reset_for_tests() -> None:
    """Drop EVERYTHING: ``_NLP`` singleton, memo, and pipe-call counter.

    Use this only in tests that exercise the auto-download branch — they
    need ``spacy.load`` to be called again. Sibling tests pay for the
    spaCy reload, so don't use this casually.
    """
    global _NLP  # noqa: PLW0603
    _NLP = None
    _reset_cache_for_tests()


__all__ = [
    "KERNEL_VERSION_TAG",
    "MODEL_NAME",
    "MorphAnalysis",
    "_reset_cache_for_tests",
    "_reset_for_tests",
    "_stats",
    "compute_morph_analysis",
    "evidence_ref_for",
]
