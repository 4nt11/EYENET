"""Provider-agnostic contracts for the LLM advisory stage.

The LLM is a **flag-only tripwire + analyst** (CLASSIFIER_PLAN §3/§4): it catches
*semantic* sensitivity the deterministic stages cannot ("describes an undercover
operation" — no PII, no banner, maximally sensitive) and produces a short
human-readable analysis, but it **NEVER changes the binding tier**. It can only
raise an ``operator_review`` flag.

``BaseProvider`` is the abstract transport — one ``generate`` call, text in,
text out. It deliberately knows nothing about repair, retry, schemas, or tiers:
all of that lives in the provider-agnostic :mod:`._advise` / :mod:`._repair`
layer so a second provider is a thin subclass, never a re-implementation. This
is the same env-dispatched abstract-factory shape as ``storage/`` (see
:mod:`.factory`); ``abc.ABC`` *is* the abstract metaclass — EYENET uses no custom
metaclass anywhere.

**Containment story (why this is HTTP, not nsjail).** The only thing that ever
crosses to the model is the already-extracted plain text (``ExtractResult.text``
from the Slice-1 chokepoint) — never the document bytes, a path, a tool, or a
file handle. The model is a pure text→text function with no tools. There is no
untrusted-code-execution surface to jail; the single threat is prompt injection
of the *output*, handled by fencing the doc as DATA (:mod:`._prompt`) and
treating the output as hostile (:mod:`._repair`, :mod:`._sanitize`). The worst a
fully-injected output can do is *suppress* a flag → the binding deterministic
tier stands → safe per §0. **Injection can never lower classification.**
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Sequence

    from eyenet.contracts.enums import SensitivityTier

__all__ = [
    "BaseProvider",
    "LlmAdvisory",
    "LlmUnavailable",
    "Msg",
    "ProviderTimeoutError",
    "ProviderUnavailableError",
]


class ProviderUnavailableError(Exception):
    """The provider could not be reached / refused / 4xx-5xx'd — do NOT retry.

    Connection refused, daemon down, model-not-found: re-prompting is pointless.
    The orchestrator maps this straight to :class:`LlmUnavailable`.
    """


class ProviderTimeoutError(Exception):
    """A single ``generate`` call exceeded its timeout — MAY be retried.

    Distinct from :class:`ProviderUnavailableError`: a transient slow turn is
    worth one more attempt within the configured budget.
    """


@dataclass(frozen=True, slots=True)
class Msg:
    """One chat turn handed to the provider. ``content`` is never executed."""

    role: Literal["system", "user"]
    content: str


@dataclass(frozen=True, slots=True)
class LlmAdvisory:
    """The advisory verdict: a tripwire tier PLUS a human-readable analysis.

    ``suggested_tier`` drives the tripwire (a flag fires only if it exceeds the
    binding deterministic tier). ``summary`` + ``indicators`` are the analysis /
    context deliverable — neutralized at the data-model boundary (:mod:`._sanitize`)
    so a downstream sink cannot be tricked by a ``<script>`` payload. ``model`` /
    ``truncated_input`` / ``attempts`` are filled by the orchestrator, not parsed
    from (untrusted) model output.
    """

    suggested_tier: SensitivityTier
    summary: str  # SANITIZED, bounded
    indicators: tuple[str, ...]  # SANITIZED, bounded, capped count
    confidence: Literal["low", "medium", "high"]
    model: str = ""  # provider-reported (config), set by the orchestrator
    truncated_input: bool = False  # the text was clipped before sending
    attempts: int = 1

    def redacted(self) -> LlmAdvisory:
        """Drop the free-text analysis — the audit log is not clearance-gated.

        ``summary`` / ``indicators`` paraphrase document content and may quote
        sensitive spans, so they never reach the open audit row; only the
        tier/confidence/model metadata does.
        """
        return replace(self, summary="[redacted]", indicators=())


@dataclass(frozen=True, slots=True)
class LlmUnavailable:
    """The advisory could not be produced (down, timed out, unparseable).

    Tier is unchanged regardless — the deterministic floors bind. The merge
    raises an informational ``LLM_UNAVAILABLE`` flag so a human knows the
    semantic tripwire did not deploy on this document (§0).
    """

    reason: str  # provider_unavailable | timeout | unparseable_after_retries | remote_not_allowed
    detail: str
    attempts: int


class BaseProvider(ABC):
    """Abstract LLM transport. ONE responsibility: messages in, raw text out.

    Concrete providers (``impl/ollama.py``, future cloud backends) translate
    their wire/SDK errors into :class:`ProviderUnavailable` / :class:`ProviderTimeout`
    so the orchestrator stays provider-agnostic. They do NOT parse, repair, or
    interpret the output — that is the shared :mod:`._advise` layer's job.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Stable provider identifier, e.g. ``"ollama"``."""

    @property
    @abstractmethod
    def model(self) -> str:
        """The configured model name (operator-controlled, trusted)."""

    @property
    @abstractmethod
    def is_local(self) -> bool:
        """True iff the endpoint is loopback — the egress guard (see ._advise)."""

    @abstractmethod
    async def generate(
        self,
        messages: Sequence[Msg],
        *,
        json_schema: dict[str, object],
        timeout_s: float,
    ) -> str:
        """Run one completion and return the raw assistant text (untrusted).

        ``json_schema`` is the structured-output grammar (first line of defense
        against malformed JSON); the caller still repairs + validates the result.
        Raises :class:`ProviderUnavailable` (don't retry) or
        :class:`ProviderTimeout` (may retry).
        """
