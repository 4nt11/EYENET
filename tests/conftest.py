"""Top-level test fixtures shared across the whole test tree.

Session-level checks that must run BEFORE any test collects or executes
live here. Subtree-specific fixtures (e.g. the per-test cache reset in
``tests/unit/sensor/primitives/conftest.py``) stay closer to where
they're needed.
"""

from __future__ import annotations

import pytest


@pytest.fixture(scope="session", autouse=True)
def _ensure_spacy_es_model() -> None:
    """Fail fast if the Spanish spaCy model isn't installed locally.

    EYENET's production kernel (``_locale_morph_kernel.py``) lazy-fetches
    ``es_core_news_sm`` on first use, which is fine for a developer with
    network access. CI environments (sandboxed, network-restricted, or
    deliberately offline) instead get a clear remediation message at
    suite start rather than a cascade of confusing OSError traces from
    every M6.5 test.

    The fixture does NOT auto-download in tests — tests must be hermetic
    and a network round-trip at the start of every CI run is the wrong
    place to hide that cost. The kernel handles the download path in
    production code; CI is expected to pre-provision via
    ``python scripts/install_models.py`` (or equivalent).
    """
    try:
        import spacy

        spacy.load("es_core_news_sm", disable=["parser", "ner"])
    except OSError as exc:
        pytest.exit(
            "Spanish spaCy model not installed.\n"
            "Run: uv run python scripts/install_models.py\n"
            f"(spaCy error: {exc})",
            returncode=2,
        )
