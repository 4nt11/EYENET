"""Drive the jailed Presidio NER pass and map its findings to a tier floor.

This is the Presidio stage's public entry. The heavy NER (presidio-analyzer +
spaCy es/en) runs ONLY inside nsjail — presidio is a jail-only ``[extract]`` dep,
never imported into the main app (see ``pyproject.toml``). We feed the
already-extracted text back through the Slice-1 chokepoint to a worker in the
``eyenet-extract`` venv, which returns a bounded JSON envelope of PII findings.

Fail-closed by construction (CLASSIFIER_PLAN §0): a missing venv, a degraded
sandbox, an OOM / timeout / seccomp kill, or unparseable output all yield a
``fail_closed`` verdict pinned to CLASSIFIED. A heavy spaCy pass on a 200-page or
adversarial document that blows the memory/time budget is *contained* — the same
``RLIMIT_AS`` / ``time_limit`` guarantee extraction already has — and the
document is forced to the top tier pending operator review, never silently
under-classified.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from eyenet.classifier.sandbox import (
    ExtractResult,
    SandboxLimits,
    extract_sandboxed,
    venv_profile,
)
from eyenet.contracts.enums import SensitivityTier

from ._loader import load_pii_map
from ._mapping import map_findings
from ._types import PiiFinding, PresidioVerdict

if TYPE_CHECKING:
    from ._types import PiiMap

__all__ = ["PRESIDIO_LIMITS", "detect"]

_log = structlog.get_logger()

_WORKER_PATH = str(Path(__file__).parent / "_workers" / "presidio_worker.py")

# Presidio + spaCy NER is heavier than the document parsers: the sm models and
# thinc/numpy runtime need more address space and CPU than the extraction
# default. Bumped from DEFAULT_LIMITS; tune from real runs, do not guess blindly.
# parent_timeout_s must exceed time_limit_s (SandboxLimits enforces this).
PRESIDIO_LIMITS = SandboxLimits(
    rlimit_as_mb=2048,
    rlimit_cpu_s=55,
    time_limit_s=60,
    parent_timeout_s=75,
)


def _fail_closed(map_version: str, *, reason: str) -> PresidioVerdict:
    """Build the §0 fail-closed verdict — CLASSIFIED, no matches, flagged."""
    _log.error("classify.presidio_fail_closed", reason=reason, map_version=map_version)
    return PresidioVerdict(
        tier_floor=SensitivityTier.CLASSIFIED,
        matches=(),
        map_version=map_version,
        fail_closed=True,
    )


def _parse_findings(meta: dict[str, object]) -> list[PiiFinding] | None:
    """Decode the worker envelope's ``meta["findings"]`` into typed findings.

    Returns None on any shape mismatch — an OK jail exit with a malformed
    findings list is a fail-closed signal, not an empty (NORMAL) document.
    """
    raw = meta.get("findings")
    if not isinstance(raw, list):
        return None
    findings: list[PiiFinding] = []
    for item in raw:
        if not isinstance(item, dict):
            return None
        try:
            findings.append(
                PiiFinding(
                    entity_type=str(item["entity_type"]),
                    start=int(item["start"]),
                    end=int(item["end"]),
                    score=float(item["score"]),
                    language=str(item["language"]),
                    text=str(item["text"]),
                )
            )
        except (KeyError, TypeError, ValueError):
            return None
    return findings


def detect(
    text: str,
    *,
    pii_map: PiiMap | None = None,
    limits: SandboxLimits = PRESIDIO_LIMITS,
) -> PresidioVerdict:
    """Run the jailed Presidio NER pass over ``text`` and return a tier floor.

    ``pii_map`` defaults to the bundled/override map. Returns a ``fail_closed``
    CLASSIFIED verdict if the extract venv is absent or the jailed pass fails
    in any way.
    """
    resolved_map = pii_map if pii_map is not None else load_pii_map()

    profile = venv_profile()
    if profile is None:
        return _fail_closed(resolved_map.map_version, reason="extract_venv_unavailable")

    result = extract_sandboxed(
        text.encode("utf-8"),
        worker_path=_WORKER_PATH,
        limits=limits,
        profile=profile,
        interpret="envelope",
    )
    if not isinstance(result, ExtractResult):
        return _fail_closed(resolved_map.map_version, reason=result.reason.value)

    findings = _parse_findings(result.meta)
    if findings is None:
        return _fail_closed(resolved_map.map_version, reason="bad_findings_envelope")

    verdict = map_findings(findings, resolved_map)
    # Provenance for the operational log — counts + offsets + tier, NEVER the raw
    # matched spans (logs are not clearance-gated).
    _log.info(
        "classify.presidio",
        map_version=verdict.map_version,
        engine="presidio",
        tier_floor=verdict.tier_floor.value,
        n_findings=len(findings),
        n_matches=len(verdict.matches),
        entities=sorted({m.entity_type for m in verdict.matches}),
    )
    return verdict
