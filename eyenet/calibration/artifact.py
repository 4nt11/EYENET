"""Calibration artifact — hash-pinned, committed, regression-tested.

The artifact captures the full output of one calibration run: simhash grid
results (within/cross histograms, AUC, chosen thresholds), recipe grid
results (axes, confusion matrices, P/R/F1), and provenance (corpus sha256,
EYENET version, BEHAVE-TEXT version, generation timestamp). It is JSON,
committed to ``tests/fixtures/calibration/``, and asserted against by the
calibration test suite.

A ``self_hash`` field at the bottom carries the sha256 of all other fields
in canonical JSON form. Edit detection is trivial — any field change
without recomputing the hash fails the regression test.

The artifact intentionally carries NO message bodies, NO usernames, NO
raw evidence_refs. Only:

* numeric distance distributions (anonymous pairs),
* opaque sender_ids (pseudonymous integers),
* threshold values,
* provenance hashes.

That makes the artifact safe to commit even though the corpus itself is
gitignored.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from .recipes_grid import RecipeCalibration
from .simhash_grid import GridResult, PrimitiveGridResult

ARTIFACT_SCHEMA_VERSION: str = "1.0"
"""Bumped on breaking artifact-shape changes. Tests pin to exact version."""

_ES_DISABLED_PRIMITIVES: frozenset[str] = frozenset(
    {
        # M5 disable (2026-05-22): AUC=0.55, precision floor unreached.
        "function_word_distribution_top50",
        # M5 disable (2026-05-22): AUC=0.68, precision floor unreached.
        "character_ngram_simhash",
        # M6.5 disable (2026-05-23): AUC=0.61, precision floor unreached.
        "pos_ngram_signature",
        # M6.5 disable (2026-05-23): AUC=0.63, precision floor unreached.
        "optional_grammar_signature",
    }
)
"""Simhash primitives that the operator has disabled for Spanish.

Spanish disable is operator policy, not a calibration accident: every
simhash primitive evaluated against the Rutify corpus has failed to
clear the 0.70 precision floor at any threshold. The within/cross
Hamming distributions overlap too much on short Spanish chat. Long-term
fix is BEHAVE-TEXT 0.0.2's minhash-with-shingles (which can be tuned
for short text) and/or the LLM-Confirmer; until those land, Spanish
linkage is driven by the recipe layer + operator review queue.

Adding a new primitive here means: artifact records ``enabled=False``
for its Spanish slice, ``LinkerThresholds`` should ship ``{"es": None}``
for that primitive's per-lang dict (so the Linker skips the comparator
entirely), and the calibration regression tests assert the disable."""


@dataclass(frozen=True)
class SimhashArtifactEntry:
    """One simhash primitive's calibration outcome for a language slice."""

    primitive: str
    language: str | None
    enabled: bool  # False when comparator is disabled for this language
    actors_fired: int
    within_count: int
    within_min: int
    within_p50: int
    within_max: int
    cross_count: int
    cross_min: int
    cross_p50: int
    cross_max: int
    auc: float
    strategy: str
    chosen_threshold: int | None  # None when disabled
    chosen_precision: float
    chosen_recall: float
    chosen_f1: float
    f1_max_threshold: int
    f1_max_f1: float


@dataclass(frozen=True)
class RecipeArtifactEntry:
    """One recipe's calibration outcome on the labeled set."""

    name: str
    version: str
    positive_label: str
    strategy: str
    axes: tuple[dict[str, object], ...]  # serialized AxisGroup list
    groups_count: int
    tp: int
    fp: int
    tn: int
    fn: int
    precision: float
    recall: float
    f1: float
    notes: tuple[str, ...]


@dataclass(frozen=True)
class CalibrationArtifact:
    """Top-level artifact written to ``rutify_calibration_baseline.json``."""

    schema_version: str
    corpus_id: str
    corpus_sha256: str
    eyenet_version: str
    behave_text_version: str
    generated_at: str  # ISO8601 UTC
    actor_count_total: int
    actor_count_simhash_qualifying: int  # actors >= min_messages
    min_messages: int
    labeler: str
    label_counts: dict[str, int]
    simhash: tuple[SimhashArtifactEntry, ...]
    recipes: tuple[RecipeArtifactEntry, ...]
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_canonical_dict(self) -> dict[str, object]:
        """Dict view used for hashing and serialization (sorted keys)."""
        return asdict(self)

    def compute_self_hash(self) -> str:
        """sha256 over the canonical JSON of all fields."""
        payload = json.dumps(self.to_canonical_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _percentile_or_zero(sorted_vals: list[int], pct: int) -> int:
    if not sorted_vals:
        return 0
    k = max(0, min(len(sorted_vals) - 1, (pct * (len(sorted_vals) - 1)) // 100))
    return sorted_vals[k]


def _simhash_entry(p: PrimitiveGridResult, *, enabled: bool) -> SimhashArtifactEntry:
    within = sorted(p.within_distances)
    cross = sorted(p.cross_distances)
    return SimhashArtifactEntry(
        primitive=p.primitive,
        language=p.language,
        enabled=enabled,
        actors_fired=p.actors_fired,
        within_count=len(within),
        within_min=within[0] if within else 0,
        within_p50=_percentile_or_zero(within, 50),
        within_max=within[-1] if within else 0,
        cross_count=len(cross),
        cross_min=cross[0] if cross else 0,
        cross_p50=_percentile_or_zero(cross, 50),
        cross_max=cross[-1] if cross else 0,
        auc=p.auc,
        strategy=p.strategy,
        chosen_threshold=p.chosen_threshold if enabled else None,
        chosen_precision=p.chosen_precision,
        chosen_recall=p.chosen_recall,
        chosen_f1=p.chosen_f1,
        f1_max_threshold=p.f1_max_threshold,
        f1_max_f1=p.f1_max_f1,
    )


def _recipe_entry(rc: RecipeCalibration) -> RecipeArtifactEntry:
    axes_payload: list[dict[str, object]] = []
    for group in rc.groups:
        axes_payload.append(
            {"axes": [{"feature": a.feature, "op": a.op, "value": a.value} for a in group.axes]}
        )
    return RecipeArtifactEntry(
        name=rc.name,
        version=rc.version,
        positive_label=rc.positive_label,
        strategy=rc.strategy,
        axes=tuple(axes_payload),
        groups_count=len(rc.groups),
        tp=rc.tp,
        fp=rc.fp,
        tn=rc.tn,
        fn=rc.fn,
        precision=rc.precision,
        recall=rc.recall,
        f1=rc.f1,
        notes=rc.notes,
    )


def build(
    *,
    corpus_id: str,
    corpus_sha256: str,
    actor_count_total: int,
    actor_count_simhash_qualifying: int,
    min_messages: int,
    labeler: str,
    label_counts: dict[str, int],
    simhash_grid: GridResult,
    simhash_es_disabled: bool,
    recipe_results: list[RecipeCalibration],
    notes: tuple[str, ...] = (),
) -> CalibrationArtifact:
    """Construct the artifact dataclass (does not write to disk).

    ``simhash_es_disabled`` reflects the operator decision (PLAN §M5,
    2026-05-22): when True, simhash entries for language ``es`` carry
    ``enabled=False`` and ``chosen_threshold=None``. The artifact still
    records the grid output for posterity.
    """
    eyenet_version = _safe_version("eyenet")
    behave_text_version = _safe_version("behave-text")

    simhash_entries: list[SimhashArtifactEntry] = []
    for p in simhash_grid.per_primitive:
        is_es_slice = p.language == "es"
        # ``simhash_es_disabled`` is the CLI flag; ``_ES_DISABLED_PRIMITIVES``
        # is the operator policy list. A primitive is recorded as
        # disabled in the artifact iff BOTH apply — the operator chose
        # to record the disable AND the primitive is on the policy list.
        # M6.5 calibration (2026-05-23) added pos_ngram + optional_grammar
        # to the policy list after their AUC failed to clear the
        # precision floor against Rutify.
        is_es_disabled_primitive = p.primitive in _ES_DISABLED_PRIMITIVES
        enabled = not (simhash_es_disabled and is_es_slice and is_es_disabled_primitive)
        simhash_entries.append(_simhash_entry(p, enabled=enabled))

    return CalibrationArtifact(
        schema_version=ARTIFACT_SCHEMA_VERSION,
        corpus_id=corpus_id,
        corpus_sha256=corpus_sha256,
        eyenet_version=eyenet_version,
        behave_text_version=behave_text_version,
        generated_at=datetime.now(tz=UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        actor_count_total=actor_count_total,
        actor_count_simhash_qualifying=actor_count_simhash_qualifying,
        min_messages=min_messages,
        labeler=labeler,
        label_counts=dict(sorted(label_counts.items())),
        simhash=tuple(simhash_entries),
        recipes=tuple(_recipe_entry(rc) for rc in recipe_results),
        notes=notes,
    )


def write(artifact: CalibrationArtifact, path: Path) -> str:
    """Serialize artifact + computed self_hash to a JSON file.

    Returns the self_hash (same value stored in the file).
    """
    payload = artifact.to_canonical_dict()
    self_hash = artifact.compute_self_hash()
    payload["self_hash"] = self_hash
    path.write_text(
        json.dumps(payload, sort_keys=True, indent=2, separators=(",", ": ")) + "\n",
        encoding="utf-8",
    )
    return self_hash


def load(path: Path) -> tuple[CalibrationArtifact, str]:
    """Load an artifact + its stored self_hash. Caller verifies the match."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        msg = f"artifact root is not a JSON object: {type(raw).__name__}"
        raise ValueError(msg)
    typed: dict[str, object] = {}
    for k, v in raw.items():
        if not isinstance(k, str):
            msg = f"artifact root: non-string key {k!r}"
            raise ValueError(msg)
        typed[k] = v
    stored_hash_obj = typed.pop("self_hash", "")
    stored_hash = stored_hash_obj if isinstance(stored_hash_obj, str) else ""
    artifact = _from_dict(typed)
    return artifact, stored_hash


def _as_str(d: dict[str, object], key: str) -> str:
    v = d.get(key)
    if not isinstance(v, str):
        msg = f"artifact field {key!r}: expected string, got {type(v).__name__}"
        raise ValueError(msg)
    return v


def _as_int(d: dict[str, object], key: str) -> int:
    v = d.get(key)
    if not isinstance(v, int) or isinstance(v, bool):
        msg = f"artifact field {key!r}: expected int, got {type(v).__name__}"
        raise ValueError(msg)
    return v


def _as_float(d: dict[str, object], key: str) -> float:
    v = d.get(key)
    if isinstance(v, bool) or not isinstance(v, int | float):
        msg = f"artifact field {key!r}: expected number, got {type(v).__name__}"
        raise ValueError(msg)
    return float(v)


def _as_bool(d: dict[str, object], key: str) -> bool:
    v = d.get(key)
    if not isinstance(v, bool):
        msg = f"artifact field {key!r}: expected bool, got {type(v).__name__}"
        raise ValueError(msg)
    return v


def _as_optional_int(d: dict[str, object], key: str) -> int | None:
    v = d.get(key)
    if v is None:
        return None
    if not isinstance(v, int) or isinstance(v, bool):
        msg = f"artifact field {key!r}: expected int or null, got {type(v).__name__}"
        raise ValueError(msg)
    return v


def _as_optional_str(d: dict[str, object], key: str) -> str | None:
    v = d.get(key)
    if v is None:
        return None
    if not isinstance(v, str):
        msg = f"artifact field {key!r}: expected string or null, got {type(v).__name__}"
        raise ValueError(msg)
    return v


def _as_str_int_dict(d: dict[str, object], key: str) -> dict[str, int]:
    v = d.get(key, {})
    if not isinstance(v, dict):
        msg = f"artifact field {key!r}: expected object, got {type(v).__name__}"
        raise ValueError(msg)
    out: dict[str, int] = {}
    for k, val in v.items():
        if not isinstance(k, str):
            msg = f"artifact field {key!r}: non-string key {k!r}"
            raise ValueError(msg)
        if not isinstance(val, int) or isinstance(val, bool):
            msg = f"artifact field {key!r}[{k!r}]: expected int"
            raise ValueError(msg)
        out[k] = val
    return out


def _as_str_tuple(d: dict[str, object], key: str) -> tuple[str, ...]:
    v = d.get(key, [])
    if not isinstance(v, list):
        msg = f"artifact field {key!r}: expected array, got {type(v).__name__}"
        raise ValueError(msg)
    out: list[str] = []
    for item in v:
        if not isinstance(item, str):
            msg = f"artifact field {key!r}: non-string element {item!r}"
            raise ValueError(msg)
        out.append(item)
    return tuple(out)


def _as_dict_list(d: dict[str, object], key: str) -> list[dict[str, object]]:
    v = d.get(key, [])
    if not isinstance(v, list):
        msg = f"artifact field {key!r}: expected array, got {type(v).__name__}"
        raise ValueError(msg)
    out: list[dict[str, object]] = []
    for item in v:
        if not isinstance(item, dict):
            msg = f"artifact field {key!r}: non-object element"
            raise ValueError(msg)
        # JSON keys are always strings in Python's json module; assert anyway.
        typed: dict[str, object] = {}
        for k, val in item.items():
            if not isinstance(k, str):
                msg = f"artifact field {key!r}: non-string key {k!r}"
                raise ValueError(msg)
            typed[k] = val
        out.append(typed)
    return out


def _coerce_simhash(r: dict[str, object]) -> SimhashArtifactEntry:
    return SimhashArtifactEntry(
        primitive=_as_str(r, "primitive"),
        language=_as_optional_str(r, "language"),
        enabled=_as_bool(r, "enabled"),
        actors_fired=_as_int(r, "actors_fired"),
        within_count=_as_int(r, "within_count"),
        within_min=_as_int(r, "within_min"),
        within_p50=_as_int(r, "within_p50"),
        within_max=_as_int(r, "within_max"),
        cross_count=_as_int(r, "cross_count"),
        cross_min=_as_int(r, "cross_min"),
        cross_p50=_as_int(r, "cross_p50"),
        cross_max=_as_int(r, "cross_max"),
        auc=_as_float(r, "auc"),
        strategy=_as_str(r, "strategy"),
        chosen_threshold=_as_optional_int(r, "chosen_threshold"),
        chosen_precision=_as_float(r, "chosen_precision"),
        chosen_recall=_as_float(r, "chosen_recall"),
        chosen_f1=_as_float(r, "chosen_f1"),
        f1_max_threshold=_as_int(r, "f1_max_threshold"),
        f1_max_f1=_as_float(r, "f1_max_f1"),
    )


def _coerce_recipe(r: dict[str, object]) -> RecipeArtifactEntry:
    return RecipeArtifactEntry(
        name=_as_str(r, "name"),
        version=_as_str(r, "version"),
        positive_label=_as_str(r, "positive_label"),
        strategy=_as_str(r, "strategy"),
        axes=tuple(_as_dict_list(r, "axes")),
        groups_count=_as_int(r, "groups_count"),
        tp=_as_int(r, "tp"),
        fp=_as_int(r, "fp"),
        tn=_as_int(r, "tn"),
        fn=_as_int(r, "fn"),
        precision=_as_float(r, "precision"),
        recall=_as_float(r, "recall"),
        f1=_as_float(r, "f1"),
        notes=_as_str_tuple(r, "notes"),
    )


def _from_dict(d: dict[str, object]) -> CalibrationArtifact:
    return CalibrationArtifact(
        schema_version=_as_str(d, "schema_version"),
        corpus_id=_as_str(d, "corpus_id"),
        corpus_sha256=_as_str(d, "corpus_sha256"),
        eyenet_version=_as_str(d, "eyenet_version"),
        behave_text_version=_as_str(d, "behave_text_version"),
        generated_at=_as_str(d, "generated_at"),
        actor_count_total=_as_int(d, "actor_count_total"),
        actor_count_simhash_qualifying=_as_int(d, "actor_count_simhash_qualifying"),
        min_messages=_as_int(d, "min_messages"),
        labeler=_as_str(d, "labeler"),
        label_counts=_as_str_int_dict(d, "label_counts"),
        simhash=tuple(_coerce_simhash(s) for s in _as_dict_list(d, "simhash")),
        recipes=tuple(_coerce_recipe(r) for r in _as_dict_list(d, "recipes")),
        notes=_as_str_tuple(d, "notes"),
    )


def _safe_version(pkg_name: str) -> str:
    try:
        return importlib.metadata.version(pkg_name)
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def corpus_sha256(path: Path) -> str:
    """Compute the sha256 of a corpus file (for artifact provenance)."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


__all__ = [
    "ARTIFACT_SCHEMA_VERSION",
    "CalibrationArtifact",
    "RecipeArtifactEntry",
    "SimhashArtifactEntry",
    "build",
    "corpus_sha256",
    "load",
    "write",
]
