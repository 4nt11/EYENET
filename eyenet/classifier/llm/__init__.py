"""LLM advisory stage — a flag-only semantic tripwire + document analyst.

Stage 4 of the classifier (CLASSIFIER_PLAN §3/§4). Where the deterministic
stages (regex, Presidio) BIND the tier, the LLM only *advises*: it catches
semantic sensitivity nothing else can and writes a short analysis, but it can
never change the binding tier — at most it raises an ``operator_review`` flag.

Containment is HTTP-to-daemon, not nsjail: only the already-extracted plain text
crosses to the model (no bytes, no tools, no file handles), so the sole threat is
prompt injection of the *output* — neutralized by fencing the doc as DATA
(:mod:`._prompt`), defensively repairing the JSON (:mod:`._repair`), and
sanitizing every free-text field (:mod:`._sanitize`). The provider is chosen by
``EYENET_LLM_PROVIDER`` (env, default ``ollama``) through the abstract factory.

Typical use::

    outcome = await advise(extract_result.text)     # LlmAdvisory | LlmUnavailable
    verdict = apply_llm_advisory(verdict, outcome)   # aggregate/: flag-only merge

Merging the advisory into the :class:`~eyenet.classifier.aggregate.ClassificationVerdict`
(flag-only, tier never lowered) lives in the aggregator package. ``advise`` is the
only I/O here and is fully unit-testable against a fake :class:`BaseProvider`.
"""

from __future__ import annotations

from ._advise import advise
from ._loader import LLM_CONFIG_ENV, LlmConfig, load_llm_config
from ._repair import RepairError, parse_advisory
from ._sanitize import sanitize_model_text
from .base import (
    BaseProvider,
    LlmAdvisory,
    LlmUnavailable,
    Msg,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from .factory import get_provider

__all__ = [
    "LLM_CONFIG_ENV",
    "BaseProvider",
    "LlmAdvisory",
    "LlmConfig",
    "LlmUnavailable",
    "Msg",
    "ProviderTimeoutError",
    "ProviderUnavailableError",
    "RepairError",
    "advise",
    "get_provider",
    "load_llm_config",
    "parse_advisory",
    "sanitize_model_text",
]
