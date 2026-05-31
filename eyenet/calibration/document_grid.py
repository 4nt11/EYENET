"""Document-classifier calibration grid — offline replay of the tier pipeline.

Slice 9. Pure and deterministic: replays the deterministic classification path
(regex over text + escalate-only metadata regex + Presidio ``map_findings`` over
the captured sidecar) over a labeled corpus and scores it. No nsjail, no LLM, no
DB — the regex engine runs in-process and the Presidio findings are pre-captured
(see :mod:`eyenet.calibration.document_corpus`), so the whole grid is CI-runnable.

The **headline metric is the under-classification (false-negative) rate** — a
labeled-sensitive document the pipeline scored *below* its true tier. That is the
one catastrophic error direction (CLASSIFIER_PLAN §0): over-classification merely
annoys an operator, under-classification leaks. So the operating-point strategy
is the §0-correct INVERSE of the M5/M8 precision-floor: minimize under-class
first, then minimize over-class as the secondary cost.

The grid does NOT call the advisory LLM (flag-only; never moves the tier) and
does NOT exercise the fail-closed path (every labeled sample is a readable
document — fail-closed is a §0 invariant, not a calibration target). It sweeps
the Presidio density cut-offs (``restricted_at`` / ``classified_at``) because
those are the tunable integers; regex rules are on/off via the TOML ``enabled``
flag, so their behaviour is reported as per-rule firing tables rather than swept.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from eyenet.classifier.presidio import map_findings
from eyenet.classifier.ruleset import classify
from eyenet.classifier.ruleset._types import max_tier
from eyenet.contracts.enums import SensitivityTier

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from eyenet.classifier.presidio._types import PiiFinding, PiiMap
    from eyenet.classifier.ruleset._types import CompiledRuleset

    from .document_corpus import DocumentSample

__all__ = [
    "ConfusionCell",
    "DensitySweepRow",
    "DocumentGridResult",
    "PiiTypeHit",
    "RuleFiring",
    "SampleOutcome",
    "meta_text",
    "run",
]

# Density-cutoff sweep candidates (distinct-PII-span counts). Tight + explicit so
# the committed artifact stays small and deterministic. restricted < classified.
_RESTRICTED_CANDIDATES: tuple[int, ...] = (2, 3, 4, 5, 6, 7, 8, 10)
_CLASSIFIED_CANDIDATES: tuple[int, ...] = (10, 12, 15, 20, 25, 30)

_ORDER: tuple[SensitivityTier, ...] = (
    SensitivityTier.NORMAL,
    SensitivityTier.RESTRICTED,
    SensitivityTier.CLASSIFIED,
)


def _rank(tier: SensitivityTier) -> int:
    return _ORDER.index(tier)


def meta_text(meta: Mapping[str, object]) -> str:
    """Flatten embedded metadata into a newline-joined string for the regex pass.

    Mirror of ``eyenet.classifier.ingest._meta_text`` (kept local so the
    calibration package does not import the full ingest/storage stack): walks
    keys + string leaves; numbers/bools/None carry no markings and are skipped.
    """
    parts: list[str] = []

    def _walk(value: object) -> None:
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, dict):
            for key, item in value.items():
                parts.append(str(key))
                _walk(item)
        elif isinstance(value, list):
            for item in value:
                _walk(item)

    _walk(meta)
    return "\n".join(parts)


@dataclass(frozen=True)
class SampleOutcome:
    """One sample's scored outcome — redacted by construction (no raw text)."""

    doc_id: str
    expected: SensitivityTier
    predicted: SensitivityTier
    regex_floor: SensitivityTier
    metadata_floor: SensitivityTier
    presidio_floor: SensitivityTier
    fired_rules: tuple[str, ...]
    n_pii: int

    @property
    def under_classified(self) -> bool:
        return _rank(self.predicted) < _rank(self.expected)

    @property
    def over_classified(self) -> bool:
        return _rank(self.predicted) > _rank(self.expected)


@dataclass(frozen=True)
class ConfusionCell:
    """One (expected, predicted) cell of the confusion matrix."""

    expected: SensitivityTier
    predicted: SensitivityTier
    count: int


@dataclass(frozen=True)
class DensitySweepRow:
    """One (restricted_at, classified_at) operating point and its error rates."""

    restricted_at: int
    classified_at: int
    under_rate: float
    over_rate: float
    exact_rate: float


@dataclass(frozen=True)
class RuleFiring:
    """How often a regex rule fired, split by the sample's ground-truth label.

    ``on_normal`` firings are the FP-prone signal: a marking rule firing on a
    labeled-NORMAL document is an over-classification driver (validates
    ``aggregate._FP_PRONE_RULES``). ``on_elevated`` firings are true positives.
    """

    rule_name: str
    total: int
    on_normal: int
    on_elevated: int


@dataclass(frozen=True)
class PiiTypeHit:
    """How many surviving Presidio matches of one entity type the corpus produced."""

    entity_type: str
    matches: int
    docs: int


@dataclass(frozen=True)
class DocumentGridResult:
    """The full grid outcome — the body of the committed calibration artifact."""

    n_samples: int
    under_classification_rate: float  # HEADLINE — the catastrophic direction (§0)
    over_classification_rate: float
    exact_match_rate: float
    confusion: tuple[ConfusionCell, ...]
    outcomes: tuple[SampleOutcome, ...]
    density_sweep: tuple[DensitySweepRow, ...]
    recommended_restricted_at: int
    recommended_classified_at: int
    rule_firing: tuple[RuleFiring, ...]
    pii_type_hits: tuple[PiiTypeHit, ...]
    ruleset_version: str
    map_version: str


@dataclass(frozen=True)
class _Replay:
    """Per-sample precomputed floors (density-independent) for fast sweeping."""

    sample: DocumentSample
    regex_floor: SensitivityTier
    metadata_floor: SensitivityTier
    fired_rules: tuple[str, ...]
    findings: tuple[PiiFinding, ...]


def _predict(
    regex_floor: SensitivityTier, meta_floor: SensitivityTier, presidio_floor: SensitivityTier
) -> SensitivityTier:
    """The tier a readable document settles to — MAX of the three live floors.

    Extraction floors at NORMAL for every readable sample (fail-closed is a §0
    invariant, not a calibration target), so this equals ``aggregate(...).tier``.
    """
    return max_tier((regex_floor, meta_floor, presidio_floor))


def _rates(outcomes: Sequence[SampleOutcome]) -> tuple[float, float, float]:
    n = len(outcomes)
    if n == 0:
        return (0.0, 0.0, 0.0)
    under = sum(1 for o in outcomes if o.under_classified)
    over = sum(1 for o in outcomes if o.over_classified)
    exact = n - under - over
    return (under / n, over / n, exact / n)


def run(
    samples: Sequence[DocumentSample],
    findings_by_doc: Mapping[str, tuple[PiiFinding, ...]],
    *,
    ruleset: CompiledRuleset,
    pii_map: PiiMap,
) -> DocumentGridResult:
    """Score the corpus under the default map, then sweep the density cut-offs."""
    replays: list[_Replay] = []
    for s in samples:
        regex = classify(s.text, ruleset)
        meta_regex = classify(meta_text(s.embedded_meta), ruleset)
        fired = tuple(sorted({m.rule_name for m in (*regex.matches, *meta_regex.matches)}))
        replays.append(
            _Replay(
                sample=s,
                regex_floor=regex.tier_floor,
                metadata_floor=meta_regex.tier_floor,
                fired_rules=fired,
                findings=tuple(findings_by_doc.get(s.doc_id, ())),
            )
        )

    outcomes = tuple(_score(r, pii_map) for r in replays)
    under_rate, over_rate, exact_rate = _rates(outcomes)
    sweep = _sweep(replays, pii_map)
    rec_r, rec_c = _recommend(sweep, default=(pii_map.restricted_at, pii_map.classified_at))

    return DocumentGridResult(
        n_samples=len(samples),
        under_classification_rate=under_rate,
        over_classification_rate=over_rate,
        exact_match_rate=exact_rate,
        confusion=_confusion(outcomes),
        outcomes=outcomes,
        density_sweep=sweep,
        recommended_restricted_at=rec_r,
        recommended_classified_at=rec_c,
        rule_firing=_rule_firing(replays),
        pii_type_hits=_pii_type_hits(replays, pii_map),
        ruleset_version=ruleset.version,
        map_version=pii_map.map_version,
    )


def _score(replay: _Replay, pii_map: PiiMap) -> SampleOutcome:
    presidio = map_findings(replay.findings, pii_map)
    predicted = _predict(replay.regex_floor, replay.metadata_floor, presidio.tier_floor)
    return SampleOutcome(
        doc_id=replay.sample.doc_id,
        expected=replay.sample.expected_tier,
        predicted=predicted,
        regex_floor=replay.regex_floor,
        metadata_floor=replay.metadata_floor,
        presidio_floor=presidio.tier_floor,
        fired_rules=replay.fired_rules,
        n_pii=len(presidio.matches),
    )


def _sweep(replays: Sequence[_Replay], pii_map: PiiMap) -> tuple[DensitySweepRow, ...]:
    rows: list[DensitySweepRow] = []
    for r in _RESTRICTED_CANDIDATES:
        for c in _CLASSIFIED_CANDIDATES:
            if c <= r:
                continue
            trial = replace(pii_map, restricted_at=r, classified_at=c)
            outcomes = tuple(_score(rep, trial) for rep in replays)
            under, over, exact = _rates(outcomes)
            rows.append(
                DensitySweepRow(
                    restricted_at=r,
                    classified_at=c,
                    under_rate=under,
                    over_rate=over,
                    exact_rate=exact,
                )
            )
    return tuple(rows)


def _recommend(sweep: Sequence[DensitySweepRow], *, default: tuple[int, int]) -> tuple[int, int]:
    """Pick the §0-optimal operating point: min under-class, then min over-class.

    Deterministic tie-break: lower under-rate, then lower over-rate, then higher
    exact-rate, then the smaller (restricted_at, classified_at). Falls back to the
    shipped default if the sweep is empty.
    """
    if not sweep:
        return default
    best = min(
        sweep,
        key=lambda row: (
            row.under_rate,
            row.over_rate,
            -row.exact_rate,
            row.restricted_at,
            row.classified_at,
        ),
    )
    return (best.restricted_at, best.classified_at)


def _confusion(outcomes: Sequence[SampleOutcome]) -> tuple[ConfusionCell, ...]:
    counts: dict[tuple[SensitivityTier, SensitivityTier], int] = {}
    for o in outcomes:
        counts[(o.expected, o.predicted)] = counts.get((o.expected, o.predicted), 0) + 1
    cells: list[ConfusionCell] = []
    for expected in _ORDER:
        for predicted in _ORDER:
            n = counts.get((expected, predicted), 0)
            if n:
                cells.append(ConfusionCell(expected=expected, predicted=predicted, count=n))
    return tuple(cells)


def _rule_firing(replays: Sequence[_Replay]) -> tuple[RuleFiring, ...]:
    total: dict[str, int] = {}
    on_normal: dict[str, int] = {}
    on_elevated: dict[str, int] = {}
    for rep in replays:
        elevated = rep.sample.expected_tier is not SensitivityTier.NORMAL
        for rule in rep.fired_rules:
            total[rule] = total.get(rule, 0) + 1
            if elevated:
                on_elevated[rule] = on_elevated.get(rule, 0) + 1
            else:
                on_normal[rule] = on_normal.get(rule, 0) + 1
    return tuple(
        RuleFiring(
            rule_name=rule,
            total=total[rule],
            on_normal=on_normal.get(rule, 0),
            on_elevated=on_elevated.get(rule, 0),
        )
        for rule in sorted(total)
    )


def _pii_type_hits(
    replays: Sequence[_Replay],
    pii_map: PiiMap,
) -> tuple[PiiTypeHit, ...]:
    matches: dict[str, int] = {}
    docs: dict[str, set[str]] = {}
    for rep in replays:
        presidio = map_findings(rep.findings, pii_map)
        for m in presidio.matches:
            matches[m.entity_type] = matches.get(m.entity_type, 0) + 1
            docs.setdefault(m.entity_type, set()).add(rep.sample.doc_id)
    return tuple(
        PiiTypeHit(entity_type=etype, matches=matches[etype], docs=len(docs[etype]))
        for etype in sorted(matches)
    )
