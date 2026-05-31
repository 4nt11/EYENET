"""Presidio PII stage — the second deterministic floor of the classifier.

Stage 2 of the classifier pipeline (CLASSIFIER_PLAN §2). Where the regex spine
catches STRUCTURED markers, this catches UNSTRUCTURED PII via NER (person /
location / organization entities) plus Presidio's pattern recognizers, and maps
**PII type + density + confidence → a sensitivity-tier FLOOR**.

The heavy NER (presidio-analyzer + spaCy es/en) runs ONLY inside nsjail — it is
a jail-only ``[extract]`` dependency, never imported into the main app. The
public entry :func:`detect` drives that jailed pass through the Slice-1
chokepoint and maps the returned findings with the pure, deterministic
:func:`map_findings`. A failed pass fails closed to CLASSIFIED (§0).

Typical use::

    verdict = detect(extract_result.text)    # bundled map, or the env override
    floor = verdict.tier_floor               # a FLOOR; the aggregator takes the MAX

Binding this floor to a final tier (MAX against the regex/extraction stages,
persistence, audit) belongs to the aggregator slice. The decision logic
(:func:`map_findings`, :func:`load_pii_map`) is pure and fully unit-testable
without nsjail; only :func:`detect`'s jail round-trip needs the real sandbox.
"""

from __future__ import annotations

from ._detect import PRESIDIO_LIMITS, detect, detect_findings
from ._loader import PII_MAP_ENV, load_pii_map
from ._mapping import map_findings
from ._types import EntityRule, PiiFinding, PiiMap, PresidioMatch, PresidioVerdict

__all__ = [
    "PII_MAP_ENV",
    "PRESIDIO_LIMITS",
    "EntityRule",
    "PiiFinding",
    "PiiMap",
    "PresidioMatch",
    "PresidioVerdict",
    "detect",
    "detect_findings",
    "load_pii_map",
    "map_findings",
]
