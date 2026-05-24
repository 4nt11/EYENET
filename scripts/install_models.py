"""Install all NLP models EYENET tests and production depend on.

Run via: ``uv run python scripts/install_models.py``

Models installed:
  * ``es_core_news_sm`` — Spanish small (~13MB), used by the M6.5 spaCy
    trio (``stylometric.pos_ngram_signature``, ``lexical.evaluative_morphology_density``,
    ``lexical.optional_grammar_signature``).

In production, the kernel auto-fetches the model on first use. This
script exists for CI runners that pre-provision before any test runs,
and for operators who prefer an explicit install step over an implicit
first-request network call.
"""

from __future__ import annotations

import sys

import spacy
from spacy.cli.download import download

_MODELS: tuple[str, ...] = ("es_core_news_sm",)


def main() -> int:
    for model in _MODELS:
        try:
            spacy.load(model)
            print(f"  [skip] {model} already installed")
        except OSError:
            print(f"  [fetch] {model} ...")
            download(model)
            print(f"  [ok]   {model} installed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
