"""Load + eagerly compile the regex ruleset (operator-editable TOML).

Mirrors :mod:`eyenet.identity_pool.loader`: validate the shape with a strict
pydantic model (``extra="forbid"``) and refuse to load anything malformed —
silent config errors here become *under-classification* later, which is the one
unrecoverable failure mode (CLASSIFIER_PLAN §0).

Every pattern is compiled at load time. A pattern that does not compile under
RE2 — including any use of lookaround or backreferences, which RE2 rejects —
raises :class:`ValueError` and the WHOLE ruleset is refused. We never half-load a
ruleset: a partly-applied ruleset could silently drop the one rule that would
have caught a classified marker.

Engine is google-re2: linear-time, no catastrophic backtracking on
threat-actor-authored text. ``log_errors`` is forced off so RE2's parse failures
surface as our exceptions, not as absl noise on stderr.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

import re2
import structlog
from pydantic import BaseModel, ConfigDict

from eyenet.contracts.enums import SensitivityTier

from ._types import CompiledRule, CompiledRuleset

__all__ = ["RULESET_ENV", "load_ruleset"]

_log = structlog.get_logger()

RULESET_ENV = "EYENET_CLASSIFIER_RULESET"
_BUNDLED_DEFAULT = Path(__file__).parent / "_default_rules.toml"

# Shared compile options: silence absl stderr logging (we raise instead). RE2 is
# linear-time regardless, so no per-call timeout is needed or meaningful.
_RE2_OPTIONS = re2.Options()
_RE2_OPTIONS.log_errors = False


class RuleSpec(BaseModel):
    """One operator-authored rule. Flags go inline in ``pattern`` ((?i)/(?m)/(?s))."""

    model_config = ConfigDict(extra="forbid")

    name: str
    pattern: str
    tier_floor: SensitivityTier
    lang: str | None = None
    description: str = ""
    # A disabled rule is parked: kept in the file for provenance/calibration but
    # NOT compiled or matched. Used for shape rules that fire on near-every
    # document (bare-number / hash / email shapes) — a hard tier floor there
    # collapses NORMAL into noise; their real home is density-aware scoring
    # (Presidio / aggregator). Disabling skips compilation, so a parked rule with
    # a not-yet-valid pattern never refuses the whole ruleset.
    enabled: bool = True


class RulesetFile(BaseModel):
    """Parsed shape of a ruleset TOML file."""

    model_config = ConfigDict(extra="forbid")

    ruleset_version: str
    rules: list[RuleSpec]


def _resolve_path(path: Path | None) -> Path:
    """Explicit arg wins; else the env override; else the bundled default."""
    if path is not None:
        return path
    env = os.environ.get(RULESET_ENV)
    if env:
        return Path(env)
    return _BUNDLED_DEFAULT


def _compile(spec: RuleSpec) -> CompiledRule:
    """Compile one rule, mapping any RE2 parse failure to a ValueError."""
    try:
        pattern: Any = re2.compile(spec.pattern, _RE2_OPTIONS)
    except re2.error as exc:  # lookaround/backref/syntax — fail closed at load
        raise ValueError(f"rule {spec.name!r}: pattern does not compile under RE2: {exc}") from exc
    return CompiledRule(
        name=spec.name,
        pattern=pattern,
        tier_floor=spec.tier_floor,
        lang=spec.lang,
    )


def load_ruleset(path: Path | None = None) -> CompiledRuleset:
    """Load, validate, and eagerly compile a ruleset.

    ``path=None`` loads the operator override (``EYENET_CLASSIFIER_RULESET``) if
    set, otherwise the bundled default. Raises :class:`FileNotFoundError` if the
    file is absent and :class:`ValueError` on any shape/compile/duplicate error.
    """
    resolved = _resolve_path(path)
    if not resolved.exists():
        raise FileNotFoundError(f"classifier ruleset not found: {resolved}")

    parsed = RulesetFile.model_validate(tomllib.loads(resolved.read_text("utf-8")))

    compiled: list[CompiledRule] = []
    seen: set[str] = set()
    disabled = 0
    for spec in parsed.rules:
        if spec.name in seen:
            raise ValueError(f"duplicate rule name: {spec.name!r}")
        seen.add(spec.name)
        if not spec.enabled:
            disabled += 1
            continue
        compiled.append(_compile(spec))

    _log.info(
        "classify.ruleset_loaded",
        ruleset_version=parsed.ruleset_version,
        n_rules=len(compiled),
        n_disabled=disabled,
        source=str(resolved),
    )
    return CompiledRuleset(version=parsed.ruleset_version, rules=tuple(compiled))
