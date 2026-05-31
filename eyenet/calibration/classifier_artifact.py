"""Document-classifier calibration artifact — hash-pinned, committed, regression-tested.

Slice 9, sibling of :mod:`eyenet.calibration.artifact` (the Rutify/verifier
artifact). SEPARATE on purpose: this artifact pins a DIFFERENT corpus (the
labeled *document* corpus, not the Rutify Telegram dump), so it carries its own
``corpus_sha256`` and must not share the stylometric artifact's hash.

The artifact captures one document-grid run: the headline under-classification
rate, the full confusion matrix, the density sweep + recommended operating
point, and the per-rule / per-PII-type diagnostic tables — all redacted (no raw
spans, the grid result is built from :class:`SampleOutcome`s that never carry
text). A ``self_hash`` over the canonical JSON makes any edit detectable: the
regression suite recomputes it and refuses a mismatch.

It is committed to ``tests/fixtures/calibration/`` and is safe to commit: the
corpus is fictional test data, and the artifact itself carries only tiers,
counts, rates, rule names, entity-type labels, and doc_ids — never raw spans.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from .document_grid import DocumentGridResult

ARTIFACT_SCHEMA_VERSION: str = "1.0"
"""Bumped on breaking artifact-shape changes; tests pin to the exact version."""

__all__ = [
    "ARTIFACT_SCHEMA_VERSION",
    "ClassifierCalibrationArtifact",
    "build",
    "canonical_self_hash",
    "load",
    "verify",
    "write",
]


def _safe_version(dist: str) -> str:
    try:
        return importlib.metadata.version(dist)
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


@dataclass(frozen=True)
class ClassifierCalibrationArtifact:
    """Top-level artifact written to ``classifier_calibration_baseline.json``."""

    schema_version: str
    corpus_id: str
    corpus_sha256: str
    eyenet_version: str
    generated_at: str  # ISO8601 UTC
    labeler: str
    n_samples: int
    n_finding_docs: int  # how many corpus docs have a captured findings row
    ruleset_version: str
    map_version: str
    under_classification_rate: float  # HEADLINE — the §0 catastrophic direction
    over_classification_rate: float
    exact_match_rate: float
    recommended_restricted_at: int
    recommended_classified_at: int
    # The doc_ids the DETERMINISTIC pipeline under-classifies (predicted < label).
    # These are documented known gaps — adversarial / semantic cases (OCR-mangled
    # banners, informal leaked chat) that CLASSIFIER_PLAN §3 assigns to the LLM
    # tripwire + provisional-CLASSIFIED + operator review, not to fragile regex.
    # The regression gate asserts NO NEW doc_id joins this set (no regression).
    under_classified_doc_ids: tuple[str, ...]
    grid: DocumentGridResult  # full confusion/sweep/diagnostics (asdict-serialized)
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_canonical_dict(self) -> dict[str, object]:
        """Dict view used for hashing + serialization (StrEnum leaves → values)."""
        return asdict(self)

    def compute_self_hash(self) -> str:
        return canonical_self_hash(self.to_canonical_dict())


def canonical_self_hash(payload: dict[str, object]) -> str:
    """sha256 over the canonical JSON of the payload, excluding any ``self_hash``.

    StrEnum values serialize to their string value, so a loaded plain-dict
    payload hashes identically to the in-memory dataclass form.
    """
    body = {k: v for k, v in payload.items() if k != "self_hash"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build(
    grid: DocumentGridResult,
    *,
    corpus_id: str,
    corpus_sha256: str,
    n_finding_docs: int,
    labeler: str,
    notes: tuple[str, ...] = (),
) -> ClassifierCalibrationArtifact:
    """Construct the artifact dataclass from a grid result (no disk write)."""
    return ClassifierCalibrationArtifact(
        schema_version=ARTIFACT_SCHEMA_VERSION,
        corpus_id=corpus_id,
        corpus_sha256=corpus_sha256,
        eyenet_version=_safe_version("eyenet"),
        generated_at=datetime.now(tz=UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        labeler=labeler,
        n_samples=grid.n_samples,
        n_finding_docs=n_finding_docs,
        ruleset_version=grid.ruleset_version,
        map_version=grid.map_version,
        under_classification_rate=grid.under_classification_rate,
        over_classification_rate=grid.over_classification_rate,
        exact_match_rate=grid.exact_match_rate,
        recommended_restricted_at=grid.recommended_restricted_at,
        recommended_classified_at=grid.recommended_classified_at,
        under_classified_doc_ids=tuple(o.doc_id for o in grid.outcomes if o.under_classified),
        grid=grid,
        notes=notes,
    )


def write(artifact: ClassifierCalibrationArtifact, path: Path) -> str:
    """Serialize artifact + computed self_hash to JSON. Returns the self_hash."""
    payload = artifact.to_canonical_dict()
    self_hash = artifact.compute_self_hash()
    payload["self_hash"] = self_hash
    path.write_text(
        json.dumps(payload, sort_keys=True, indent=2, separators=(",", ": "), default=str) + "\n",
        encoding="utf-8",
    )
    return self_hash


def load(path: Path) -> tuple[dict[str, object], str]:
    """Load the artifact payload + its stored self_hash (caller verifies the match).

    Returns the raw payload dict (NOT a reconstructed dataclass — the regression
    suite reads fields off it directly and re-hashes it).
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        msg = f"classifier artifact root is not a JSON object: {type(raw).__name__}"
        raise ValueError(msg)
    payload: dict[str, object] = dict(raw)
    stored = payload.pop("self_hash", "")
    stored_hash = stored if isinstance(stored, str) else ""
    return payload, stored_hash


def verify(path: Path) -> dict[str, object]:
    """Load + verify the self_hash; raise on mismatch; return the payload dict."""
    payload, stored = load(path)
    computed = canonical_self_hash(payload)
    if computed != stored:
        msg = (
            f"classifier calibration artifact self_hash mismatch:\n"
            f"  stored:   {stored}\n"
            f"  computed: {computed}\n"
            f"Re-run `eyenet calibrate classify run` to regenerate {path}."
        )
        raise ValueError(msg)
    return payload
