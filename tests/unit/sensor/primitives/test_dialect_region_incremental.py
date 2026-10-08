"""Equivalence guard for dialect_region's incremental fold.

The sensor now folds only the per-dispatch delta into cached per-actor state instead
of recomputing over the whole corpus every time. That optimization is only safe if
``finalize(fold(... in any chunking ...))`` is BIT-IDENTICAL to ``compute(full)``. These
tests pin exactly that across many chunk splits, including message-at-a-time, random
splits, empty deltas, and corpus entries whose body was never fetched (the window /
evidence_ref vs token-bag asymmetry).
"""

from __future__ import annotations

import random
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from eyenet.sensor.primitives import dialect_region as dr
from eyenet.sensor.primitives._regional_markers import REGIONAL_MARKERS

Corpus = list[tuple[datetime, UUID, str]]


def _ts(i: int) -> datetime:
    return datetime(2026, 5, 1, 12, 0, tzinfo=UTC).replace(minute=i % 60, second=i // 60 % 60)


def _obs_equal(a: object, b: object) -> bool:
    """Compare two Observations on everything EXCEPT ts (wall-clock, differs per call)."""
    if a is None or b is None:
        return a is None and b is None
    return (
        a.primitive == b.primitive  # type: ignore[attr-defined]
        and a.value == b.value  # type: ignore[attr-defined]
        and a.confidence == b.confidence  # type: ignore[attr-defined]  # exact: same float ops
        and a.source == b.source  # type: ignore[attr-defined]
        and a.evidence_ref == b.evidence_ref  # type: ignore[attr-defined]
        and a.window.start_ts == b.window.start_ts  # type: ignore[attr-defined]
        and a.window.end_ts == b.window.end_ts  # type: ignore[attr-defined]
    )


def _fold_in_chunks(corpus: Corpus, bodies: dict[str, str], sizes: list[int]) -> object:
    """Fold the corpus into state in the given chunk sizes, then finalize."""
    state = None
    i = 0
    for size in sizes:
        chunk = corpus[i : i + size]
        i += size
        chunk_bodies = {ref: bodies[ref] for _, _, ref in chunk if ref in bodies}
        state = dr.fold(state, chunk, chunk_bodies)
    # Any remainder (if sizes under-cover) folds in one last chunk.
    if i < len(corpus):
        chunk = corpus[i:]
        chunk_bodies = {ref: bodies[ref] for _, _, ref in chunk if ref in bodies}
        state = dr.fold(state, chunk, chunk_bodies)
    return dr.finalize(state) if state is not None else None


def _spanish_regional_corpus(n: int, *, drop_bodies: set[int] | None = None) -> tuple[Corpus, dict]:
    """n Spanish messages laced with one region's markers so a region actually wins.

    `drop_bodies` indexes whose corpus entry exists but whose body is NOT in the dict —
    exercising the asymmetry (window/evidence_ref use all entries; tokens use body ones).
    """
    drop = drop_bodies or set()
    region = next(iter(REGIONAL_MARKERS))
    markers = list(REGIONAL_MARKERS[region])[:3]
    text = "de la que el en " + " ".join(markers)  # Spanish gate words + region markers
    corpus: Corpus = []
    bodies: dict[str, str] = {}
    for i in range(n):
        ref = f"ref:{i}"
        corpus.append((_ts(i), uuid4(), ref))
        if i not in drop:
            bodies[ref] = text
    return corpus, bodies


@pytest.mark.unit
@pytest.mark.parametrize("n", [dr.MIN_MESSAGES, dr.MIN_MESSAGES + 5, 40, 137])
def test_incremental_matches_full_message_at_a_time(n: int) -> None:
    corpus, bodies = _spanish_regional_corpus(n)
    full = dr.compute(corpus=corpus, bodies=bodies)
    incremental = _fold_in_chunks(corpus, bodies, [1] * n)
    assert full is not None  # sanity: this corpus should emit
    assert _obs_equal(full, incremental)


@pytest.mark.unit
def test_incremental_matches_full_random_splits() -> None:
    rng = random.Random(1337)  # noqa: S311 - deterministic test split, not crypto
    corpus, bodies = _spanish_regional_corpus(80)
    full = dr.compute(corpus=corpus, bodies=bodies)
    for _ in range(50):
        sizes: list[int] = []
        remaining = len(corpus)
        while remaining > 0:
            step = rng.randint(0, remaining)  # 0 => an EMPTY delta dispatch
            sizes.append(step)
            remaining -= step
        assert _obs_equal(full, _fold_in_chunks(corpus, bodies, sizes))


@pytest.mark.unit
def test_incremental_matches_full_with_bodiless_entries() -> None:
    # Entries 3, 20, 79 (last) have no fetched body: they must still count toward the
    # window + (for the last) evidence_ref, but NOT the token bag or MIN_MESSAGES.
    corpus, bodies = _spanish_regional_corpus(80, drop_bodies={3, 20, 79})
    full = dr.compute(corpus=corpus, bodies=bodies)
    assert full is not None
    assert full.evidence_ref == "ref:79"  # last entry wins even with no body
    assert _obs_equal(full, _fold_in_chunks(corpus, bodies, [1] * 80))
    assert _obs_equal(full, _fold_in_chunks(corpus, bodies, [7, 13, 25, 35]))


@pytest.mark.unit
def test_incremental_none_cases_match() -> None:
    # Below MIN_MESSAGES: both None.
    corpus, bodies = _spanish_regional_corpus(dr.MIN_MESSAGES - 1)
    assert dr.compute(corpus=corpus, bodies=bodies) is None
    assert _fold_in_chunks(corpus, bodies, [1] * len(corpus)) is None
    # English corpus: both None (language gate).
    corpus, bodies = (
        [(_ts(i), uuid4(), f"e:{i}") for i in range(20)],
        {f"e:{i}": "the of and to a in is it you that" for i in range(20)},
    )
    assert dr.compute(corpus=corpus, bodies=bodies) is None
    assert _fold_in_chunks(corpus, bodies, [5, 5, 5, 5]) is None
