"""Lexical primitive: dialect_region.

Detects the dominant regional variety of the actor's matrix language,
expressed as a BCP-47 language-region tag (e.g. ``es-CL``, ``es-AR``,
``es-MX``). Detection is based on the density of region-exclusive lexical
markers in the actor's corpus — set intersection, not embedding inference.

Design rationale (from M6 operator decision):
  The INGEOTEC regional-spanish-models vocabulary approach works with thin
  chat corpora (10+ messages is sufficient) and is fully interpretable: you
  can see exactly which markers fired. fastText embedding-based classification
  requires 10-100+ messages to aggregate reliably and adds a model-load step.

Language-agnostic in contract: the output format ``xx-YY`` is universal and
the marker vocabulary is pluggable per language family. Spanish (Rutify
corpus) is the first calibrated language; English and Portuguese marker sets
can be added to ``_regional_markers.py`` without touching this module.

Emits the string ``unknown`` when below the confidence threshold (per
BEHAVE-TEXT registry spec) so downstream engines can distinguish
``unknown`` (below threshold) from the observation not being emitted at
all (wrong language, insufficient corpus).

Source label: ``eyenet/sensor/primitives/dialect-region:v{VERSION}#dialect-markers-v1``
Slot: ``lexical_summary.dialect_region`` (via slot_mapper.py).
"""

from __future__ import annotations

import re
import time
from datetime import datetime
from uuid import UUID

from behave_text.spec import Observation, Window

from ._locale_rules._language_gate import is_spanish
from ._regional_markers import MARKERS_VERSION, REGIONAL_MARKERS

PRIMITIVE_NAME: str = "lexical.dialect_region"
PRIMITIVE_VERSION: str = "0.1"
MARKER_VERSION_TAG: str = f"dialect-markers-{MARKERS_VERSION}"

# Minimum number of message bodies required before attempting detection.
MIN_MESSAGES: int = 10
# Minimum marker-hit rate (hits / total_tokens) to declare any region.
MIN_HIT_RATE: float = 0.001
# Required ratio of top-region rate to runner-up rate to be confident.
CONFIDENCE_MARGIN: float = 1.8
# Sentinel emitted when detection falls below the confidence threshold.
UNKNOWN_SENTINEL: str = "unknown"

# Minimum count of regions scoring above MIN_HIT_RATE before margin gate kicks in.
_MIN_RANKED_REGIONS_FOR_MARGIN: int = 2

# Language-gate moved to _locale_rules/_language_gate.py (M6.5) so the M6
# dialect_region primitive and the M6.5 spaCy trio cannot drift on what
# counts as "Spanish." Anchor sets are unchanged from M6.

_TOKENIZE = re.compile(r"[a-záéíóúüñàèìòùâêîôûäëïöü']+", re.IGNORECASE)


def _tokens(text: str) -> list[str]:
    return [m.group(0).lower() for m in _TOKENIZE.finditer(text)]


def _score_regions(token_bag: list[str]) -> dict[str, float]:
    """Return per-region marker-hit rate (hits / total_tokens)."""
    total = len(token_bag)
    if total == 0:
        return {}
    token_set = set(token_bag)
    scores: dict[str, float] = {}
    for region, markers in REGIONAL_MARKERS.items():
        hits = len(token_set & markers)
        if hits > 0:
            scores[region] = hits / total
    return scores


def compute(
    *,
    corpus: list[tuple[datetime, UUID, str]],
    bodies: dict[str, str],
) -> Observation | None:
    """Detect the actor's dominant regional variety.

    ``corpus``  — [(ts, msg_id, evidence_ref), …] from CorpusStore.iter_since
    ``bodies``  — evidence_ref → plaintext body
    Returns None when the corpus is too small or when no Spanish text detected.
    Returns an Observation with value ``unknown`` when Spanish is detected but
    below the confidence threshold.
    """
    bodies_list = [bodies[ref] for _, _, ref in corpus if ref in bodies]
    if len(bodies_list) < MIN_MESSAGES:
        return None

    token_bag: list[str] = []
    for body in bodies_list:
        token_bag.extend(_tokens(body))

    if not is_spanish(token_bag):
        return None

    scores = _score_regions(token_bag)

    ts_vals = [ts.timestamp() for ts, _, _ in corpus]
    window = Window(start_ts=min(ts_vals), end_ts=max(ts_vals))
    source = f"eyenet/sensor/primitives/dialect-region:v{PRIMITIVE_VERSION}#{MARKER_VERSION_TAG}"
    evidence_ref = corpus[-1][2] if corpus else None

    if not scores:
        return Observation(
            primitive=PRIMITIVE_NAME,
            value=UNKNOWN_SENTINEL,
            confidence=0.0,
            window=window,
            source=source,
            evidence_ref=evidence_ref,
            ts=time.time(),
        )

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    top_region, top_rate = ranked[0]

    if top_rate < MIN_HIT_RATE:
        return Observation(
            primitive=PRIMITIVE_NAME,
            value=UNKNOWN_SENTINEL,
            confidence=0.0,
            window=window,
            source=source,
            evidence_ref=evidence_ref,
            ts=time.time(),
        )

    if len(ranked) >= _MIN_RANKED_REGIONS_FOR_MARGIN:
        runner_up_rate = ranked[1][1]
        margin = top_rate / runner_up_rate if runner_up_rate > 0 else float("inf")
    else:
        margin = float("inf")

    if margin < CONFIDENCE_MARGIN:
        has_runner_up = len(ranked) >= _MIN_RANKED_REGIONS_FOR_MARGIN
        unknown_conf = top_rate / (top_rate + ranked[1][1]) if has_runner_up else 1.0
        return Observation(
            primitive=PRIMITIVE_NAME,
            value=UNKNOWN_SENTINEL,
            confidence=unknown_conf,
            window=window,
            source=source,
            evidence_ref=evidence_ref,
            ts=time.time(),
        )

    confidence = min(1.0, top_rate * 500)  # scale to [0,1]; 0.002 hit rate → conf 1.0
    return Observation(
        primitive=PRIMITIVE_NAME,
        value=top_region,
        confidence=confidence,
        window=window,
        source=source,
        evidence_ref=evidence_ref,
        ts=time.time(),
    )


__all__ = [
    "CONFIDENCE_MARGIN",
    "MARKER_VERSION_TAG",
    "MIN_HIT_RATE",
    "MIN_MESSAGES",
    "PRIMITIVE_NAME",
    "PRIMITIVE_VERSION",
    "UNKNOWN_SENTINEL",
    "compute",
]
