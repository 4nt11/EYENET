"""pytest-benchmark perf floor for the M6.5 _locale_morph_kernel.

The whole reason the M6.5 kernel exists is to share a single spaCy
tagger pass across three primitives. If a future refactor breaks the
memo or otherwise regresses kernel speed by an order of magnitude, this
test fires.

Marker scheme: ``@pytest.mark.benchmark`` is opt-in (default ``pytest -m
"unit or contract"`` skips it). Run via ``pytest -m benchmark``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from eyenet.sensor.primitives import _locale_morph_kernel as kernel
from eyenet.sensor.primitives._locale_rules.es import RULESET as ES_RULESET

# Representative corpus: 200 messages x ~80 chars each ≈ 16K of text.
# That's roughly a chatty actor's full history on a Telegram channel.
_MESSAGE = (
    "Tengo una casita muy bonita en la playa. Habiamos comido cuando le "
    "dije que se fuera. El perrito ladra mucho y la casucha es vieja."
)
_MESSAGE_COUNT = 200


def _build_corpus() -> tuple[list[tuple[datetime, UUID, str]], dict[str, str]]:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    prefix = uuid4().hex[:8]
    corpus: list[tuple[datetime, UUID, str]] = []
    bodies: dict[str, str] = {}
    for i in range(_MESSAGE_COUNT):
        ref = f"{prefix}:bench:{i}"
        corpus.append((base.replace(minute=i % 60, second=i // 60), uuid4(), ref))
        bodies[ref] = _MESSAGE
    return corpus, bodies


@pytest.mark.benchmark
@pytest.mark.slow
def test_compute_morph_analysis_under_budget(benchmark: object) -> None:
    """One full kernel pass over 200 messages should fit under 500ms.

    Local baseline at M6.5 round-2 is ~190ms on a modern laptop; 500ms
    gives ~2.6x headroom for slower CI hardware while still catching
    order-of-magnitude regressions (e.g. the memo silently breaking and
    triggering a per-message tagger load).
    """
    corpus, bodies = _build_corpus()
    # Prime spaCy once so the load isn't part of the measured cost.
    kernel._load_nlp()

    def _runner() -> kernel.MorphAnalysis | None:
        kernel._reset_cache_for_tests()
        return kernel.compute_morph_analysis(corpus=corpus, bodies=bodies, ruleset=ES_RULESET)

    result = benchmark(_runner)  # type: ignore[operator]
    assert result is not None
    # 500ms ceiling — the goal is to alert on >2.5x regressions, not to
    # micro-tune. pytest-benchmark stores per-round timings; the assert
    # below checks the mean.
    assert benchmark.stats["mean"] < 0.500  # type: ignore[attr-defined]
