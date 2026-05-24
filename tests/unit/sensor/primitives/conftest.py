"""Per-directory pytest fixtures for sensor-primitive unit tests.

The M6.5 ``_locale_morph_kernel`` carries a single-slot memo keyed on
``(language, evidence_ref tuple)``. In production the sensor builds
unique refs per actor, so the memo behaves correctly. In tests, however,
multiple test functions reuse the small ``ref:0/ref:1`` namespace via
their ``_corpus_bodies`` helpers — without an isolating fixture, a later
test would receive a cached MorphAnalysis from an earlier test's input.

The autouse fixture below resets the kernel's cache between every test
in this subtree. It's cheap (sets four module-level globals to ``None``)
and only touches state the kernel created.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from eyenet.sensor.primitives import _locale_morph_kernel as _kernel


@pytest.fixture(autouse=True)
def _reset_locale_morph_kernel_cache() -> Iterator[None]:
    # Only drop the memo + counter — keep the loaded spaCy model. Tests
    # that need a full reset (auto-download exercise) call
    # ``_reset_for_tests`` directly.
    _kernel._reset_cache_for_tests()
    yield
    _kernel._reset_cache_for_tests()
