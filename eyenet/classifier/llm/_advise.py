"""Orchestrate one advisory call: build → generate → repair → retry → bound.

This is the provider-agnostic heart of the stage (CLASSIFIER_PLAN §4's
``run_llm_advisory``). It is the only I/O-bearing function in the package, but it
holds no transport detail — it drives an abstract :class:`BaseProvider` and is
fully unit-testable against a fake one. Everything it touches (prompt, repair,
sanitize) is pure.

Failure is fail-soft, never fail-closed-on-tier: the deterministic floors bind,
so a down daemon or unparseable output yields :class:`LlmUnavailable` (the merge
turns that into an informational flag) — the tier never moves.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import structlog

from ._loader import load_llm_config
from ._prompt import build_messages, corrective_message
from ._repair import parse_advisory
from ._sanitize import sanitize_model_text
from ._schema import advisory_json_schema
from .base import (
    BaseProvider,
    LlmAdvisory,
    LlmUnavailable,
    Msg,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from .factory import get_provider

if TYPE_CHECKING:
    from ._loader import LlmConfig

__all__ = ["advise"]

_log = structlog.get_logger()

# Cap on any failure-detail string before it lands in a (renderable) flag/log.
_DETAIL_CAP = 200


def _safe(detail: str) -> str:
    """Sanitize a failure detail — it may carry model-derived text."""
    return sanitize_model_text(detail, max_len=_DETAIL_CAP)


def _clip(text: str, max_chars: int) -> tuple[str, bool]:
    """Clip text to ``max_chars`` codepoints; report whether it was truncated."""
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars], True


async def advise(
    text: str,
    *,
    provider: BaseProvider | None = None,
    cfg: LlmConfig | None = None,
) -> LlmAdvisory | LlmUnavailable:
    """Produce a semantic advisory for ``text`` (the already-extracted plain text).

    Only the text crosses to the model — no document bytes, no tools. Returns an
    :class:`LlmAdvisory` (tripwire tier + analysis) or :class:`LlmUnavailable`
    (down / timed out / unparseable). The tier is the caller's deterministic
    verdict; this never changes it.
    """
    cfg = cfg or load_llm_config()
    provider = provider or get_provider(
        model=cfg.model,
        endpoint=cfg.endpoint,
        connect_timeout_s=cfg.connect_timeout_s,
    )

    if not provider.is_local and not cfg.allow_remote:
        _log.error("classify.llm_remote_blocked", provider=provider.name, model=provider.model)
        return LlmUnavailable(
            reason="remote_not_allowed",
            detail="non-loopback endpoint with allow_remote=false",
            attempts=0,
        )

    clipped, truncated = _clip(text, cfg.max_text_chars)
    messages: list[Msg] = list(build_messages(clipped))
    schema = advisory_json_schema()

    exhausted_reason = "unparseable_after_retries"
    last_detail = ""
    for attempt in range(1, cfg.max_attempts + 1):
        try:
            raw = await provider.generate(
                tuple(messages), json_schema=schema, timeout_s=cfg.request_timeout_s
            )
        except ProviderUnavailableError as exc:
            _log.warning("classify.llm_unavailable", attempt=attempt, detail=_safe(str(exc)))
            return LlmUnavailable(
                reason="provider_unavailable", detail=_safe(str(exc)), attempts=attempt
            )
        except ProviderTimeoutError as exc:
            exhausted_reason, last_detail = "timeout", _safe(str(exc))
            _log.warning("classify.llm_timeout", attempt=attempt)
            continue

        parsed = parse_advisory(raw, cfg=cfg)
        if isinstance(parsed, LlmAdvisory):
            advisory = replace(
                parsed, model=provider.model, truncated_input=truncated, attempts=attempt
            )
            _log.info(
                "classify.llm_advised",
                provider=provider.name,
                model=provider.model,
                suggested_tier=advisory.suggested_tier.value,
                confidence=advisory.confidence,
                n_indicators=len(advisory.indicators),
                truncated_input=truncated,
                attempts=attempt,
            )
            return advisory

        # parse_advisory returns LlmAdvisory | RepairError; the advisory case
        # returned above, so this is a RepairError — re-prompt within budget.
        exhausted_reason, last_detail = "unparseable_after_retries", parsed.reason
        _log.warning("classify.llm_repair_failed", attempt=attempt, reason=parsed.reason)
        messages.append(corrective_message())

    _log.warning("classify.llm_exhausted", reason=exhausted_reason, attempts=cfg.max_attempts)
    return LlmUnavailable(reason=exhausted_reason, detail=last_detail, attempts=cfg.max_attempts)
