"""The dumb-LLM body-check: turn whatever the model emitted into a clean verdict.

Local models break JSON constantly — markdown fences, leading prose, trailing
chatter, a string where a list belongs, an invented key, a tier we never offered.
This module is the linting/repair layer: it extracts the JSON object, coerces
every field defensively, sanitizes the free text, and refuses (rather than
guesses) anything it cannot make safe. Pure and I/O-free → fully unit-testable.

A :class:`RepairError` is a soft signal to the orchestrator: re-prompt and try
again within the retry budget. An unknown ``suggested_tier`` is a RepairError,
never an upward/downward guess — the deterministic tier already binds, so a
botched advisory simply fails to flag (safe per §0).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, cast

from eyenet.contracts.enums import SensitivityTier

from ._sanitize import sanitize_model_text
from .base import LlmAdvisory

if TYPE_CHECKING:
    from ._loader import LlmConfig

__all__ = ["RepairError", "parse_advisory"]

_CONFIDENCE = frozenset({"low", "medium", "high"})


@dataclass(frozen=True, slots=True)
class RepairError:
    """The model output could not be repaired into a valid advisory."""

    reason: str


def _extract_json_object(raw: str) -> object | None:
    """Pull the first balanced ``{...}`` object out of a noisy model response.

    Strips markdown fences and any surrounding prose by brace-matching (ignoring
    braces inside strings). Returns the decoded object, or ``None`` if there is
    no parseable object.
    """
    start = raw.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    escaped = False
    for i in range(start, len(raw)):
        ch = raw[i]
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    decoded: object = json.loads(raw[start : i + 1])
                except json.JSONDecodeError:
                    return None
                return decoded
    return None


def _coerce_text(value: object) -> str:
    """Best-effort string view of an arbitrary JSON value (pre-sanitization)."""
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return str(value)


def parse_advisory(raw: str, *, cfg: LlmConfig) -> LlmAdvisory | RepairError:
    """Repair, coerce, and sanitize a raw model response into an advisory.

    Orchestration-known fields (``model`` / ``truncated_input`` / ``attempts``)
    are left at their defaults here and filled by :func:`._advise.advise`.
    """
    obj = _extract_json_object(raw)
    if not isinstance(obj, dict):
        return RepairError("no_json_object")

    tier_raw = obj.get("suggested_tier")
    if not isinstance(tier_raw, str):
        return RepairError("missing_suggested_tier")
    try:
        suggested_tier = SensitivityTier(tier_raw.strip().lower())
    except ValueError:
        # Sanitize the offending value — it is untrusted and lands in a flag detail.
        return RepairError(f"unknown_tier:{sanitize_model_text(tier_raw, max_len=24)}")

    confidence_raw = _coerce_text(obj.get("confidence")).strip().lower()
    confidence = cast(
        "Literal['low', 'medium', 'high']",
        confidence_raw if confidence_raw in _CONFIDENCE else "low",
    )

    summary = sanitize_model_text(
        _coerce_text(obj.get("summary", "")), max_len=cfg.max_summary_chars
    )

    raw_indicators = obj.get("indicators", [])
    items = raw_indicators if isinstance(raw_indicators, list) else [raw_indicators]
    indicators = tuple(
        sanitize_model_text(_coerce_text(item), max_len=cfg.max_summary_chars)
        for item in items[: cfg.max_indicators]
    )

    return LlmAdvisory(
        suggested_tier=suggested_tier,
        summary=summary,
        indicators=indicators,
        confidence=confidence,
    )
