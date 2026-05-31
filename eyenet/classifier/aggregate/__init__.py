"""Classifier aggregator — bind the deterministic floors into one tier (§4).

``aggregate(extraction, regex, presidio) -> ClassificationVerdict`` is the
single deterministic entry: a monotone ``MAX`` of the three stage floors with
court-defensible provenance. ``classification_audit_payload(verdict)`` shapes
the redacted ``eyenet.audit.classify.*`` row the ClassifierService emits later.
"""

from __future__ import annotations

from ._aggregate import aggregate
from ._audit import classification_audit_payload
from ._llm_merge import apply_llm_advisory
from ._types import ClassificationVerdict, ReviewFlag, ReviewKind, StageProvenance

__all__ = [
    "ClassificationVerdict",
    "ReviewFlag",
    "ReviewKind",
    "StageProvenance",
    "aggregate",
    "apply_llm_advisory",
    "classification_audit_payload",
]
