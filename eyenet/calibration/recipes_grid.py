"""Recipe threshold search against operator labels.

Three recipes ship in M5:

* ``lurker_or_observer`` — OR of two patterns:
   (A) replies-heavy: ``init_rate <= LURKER_MAX_INIT_RATE``
   (B) long-tail occasional presence:
       ``msg_per_day <= LURKER_MAX_MSG_PER_DAY AND corpus_span_days >= LURKER_MIN_SPAN_DAYS``
  The OR is intentional: both patterns are operator-recognized lurker
  signatures and ship as a single recipe per the M3 catalog. Thresholds
  are swept jointly: we pick the (A-threshold, B-threshold-pair) that
  maximises recall at precision >= 0.70 on the labeled set.

* ``bot_or_automated_poster`` — AND of operator-locked axes
  (PLAN §M5, 2026-05-22):
   ``init_rate >= 0.95 AND length_cv <= 0.30``
  Fixed thresholds — operator decision, not a search. Grid still computes
  confusion matrix on the labeled set so the artifact carries
  precision/recall figures and the calibration test can guard against
  regressions.

* ``chatty_member`` — NEW for M5. Single-axis ``msg_count >= T``.
  Threshold swept; pick precision_floor:0.70.

The labeled set is operator-curated; we treat it as ground truth. The
recipe code in ``eyenet.engine.recipes.*`` reads only the chosen
thresholds (constants); the artifact carries the confusion matrix +
notes for explainability.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from .interaction import ActorStats
from .labels import ActorLabel


@dataclass(frozen=True)
class AxisThreshold:
    """One feature/op/value tuple inside a recipe's threshold definition."""

    feature: str  # ActorStats field name, e.g. "init_rate"
    op: Literal["<=", ">=", "<", ">"]
    value: float

    def evaluate(self, stats: ActorStats) -> bool:
        # Runtime defence first — Literal can be bypassed via dataclass
        # construction from JSON (see artifact load path).
        if self.op not in ("<=", ">=", "<", ">"):
            msg = f"unknown op: {self.op!r}"
            raise ValueError(msg)
        v = getattr(stats, self.feature)
        if not isinstance(v, int | float):
            return False
        f = float(v)
        match self.op:
            case "<=":
                return f <= self.value
            case ">=":
                return f >= self.value
            case "<":
                return f < self.value
            case ">":
                return f > self.value


@dataclass(frozen=True)
class AxisGroup:
    """A set of axes combined with AND. Recipes are OR-of-groups."""

    axes: tuple[AxisThreshold, ...]

    def evaluate(self, stats: ActorStats) -> bool:
        return all(a.evaluate(stats) for a in self.axes)


@dataclass(frozen=True)
class RecipeCalibration:
    """Result of a single recipe's threshold search + label evaluation."""

    name: str
    version: str
    positive_label: str  # which label in the set is the recipe's positive class
    groups: tuple[AxisGroup, ...]  # recipe matches iff any group's AND fires
    strategy: str  # human-readable origin of the thresholds
    tp: int
    fp: int
    tn: int
    fn: int
    precision: float
    recall: float
    f1: float
    notes: tuple[str, ...]

    def matches(self, stats: ActorStats) -> bool:
        return any(g.evaluate(stats) for g in self.groups)


# -- Generic confusion-matrix helper ---------------------------------------


def _confusion(
    stats: list[ActorStats],
    labels: dict[int, ActorLabel],
    positive_label: str,
    predicate: Callable[[ActorStats], bool],
) -> tuple[int, int, int, int]:
    """Return (tp, fp, tn, fn) for ``predicate(stats) → predicted positive``."""
    tp = fp = tn = fn = 0
    for s in stats:
        lab = labels.get(s.sender_id)
        if lab is None:
            continue  # unlabeled; ignore
        is_positive = lab.label == positive_label
        predicted = predicate(s)
        if predicted and is_positive:
            tp += 1
        elif predicted and not is_positive:
            fp += 1
        elif not predicted and is_positive:
            fn += 1
        else:
            tn += 1
    return tp, fp, tn, fn


def _picker_prefers(
    current_best: tuple[float, int, int] | tuple[int, int, int] | None,
    candidate_tp: int,
    candidate_fp: int,
) -> bool:
    """Should we replace ``current_best`` with the candidate (tp, fp)?

    Picker order (precision-first when recall ties):
      1. Strictly higher tp (more recall).
      2. Same tp, strictly lower fp (more precision).
    Returns False when neither condition holds — keeps the existing best.
    """
    if current_best is None:
        return True
    _, best_tp, best_fp = current_best
    if candidate_tp > best_tp:
        return True
    return candidate_tp == best_tp and candidate_fp < best_fp


def _prf1(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    return round(precision, 4), round(recall, 4), round(f1, 4)


# -- Per-recipe searches ----------------------------------------------------


def search_lurker_or_observer(
    stats: list[ActorStats],
    labels: dict[int, ActorLabel],
    *,
    min_precision: float = 0.70,
) -> RecipeCalibration:
    """OR-of-two-patterns recipe: passive responder OR long-tail visitor.

    Strategy: sweep each pattern independently for its precision-floor
    threshold, then OR them. Joint precision is recomputed on the merged
    predicate. If either pattern's individual threshold cannot reach the
    precision floor, that pattern is dropped from the recipe.
    """
    # Pattern A: init_rate <= T_A. Sweep T_A from 0.05 to 1.00 step 0.05.
    a_best: tuple[float, int, int] | None = None  # (threshold, tp, fp)
    for t_a in [round(x * 0.05, 2) for x in range(1, 21)]:

        def pred_a(s: ActorStats, thr: float = t_a) -> bool:
            return s.init_rate <= thr

        tp, fp, _, _ = _confusion(stats, labels, "lurker", pred_a)
        prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        if prec >= min_precision and _picker_prefers(a_best, tp, fp):
            a_best = (t_a, tp, fp)

    # Pattern B: msg_per_day <= T_B AND corpus_span_days >= S. Sweep T_B.
    # span floor fixed at 7 days — distinguishes "long-tail occasional"
    # from "bursty short-window" actors who can't be classified as lurker.
    b_best: tuple[float, int, int] | None = None
    span_floor = 7.0
    for t_b in [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 7.0, 10.0]:

        def pred_b(s: ActorStats, thr: float = t_b, span: float = span_floor) -> bool:
            return s.msg_per_day <= thr and s.corpus_span_days >= span

        tp, fp, _, _ = _confusion(stats, labels, "lurker", pred_b)
        prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        if prec >= min_precision and _picker_prefers(b_best, tp, fp):
            b_best = (t_b, tp, fp)

    groups: list[AxisGroup] = []
    notes: list[str] = []
    if a_best is not None:
        groups.append(AxisGroup(axes=(AxisThreshold("init_rate", "<=", a_best[0]),)))
        notes.append(f"pattern_A_init_rate_max={a_best[0]} (tp={a_best[1]}, fp={a_best[2]})")
    else:
        notes.append("pattern_A_disabled: no threshold met precision floor")
    if b_best is not None:
        groups.append(
            AxisGroup(
                axes=(
                    AxisThreshold("msg_per_day", "<=", b_best[0]),
                    AxisThreshold("corpus_span_days", ">=", span_floor),
                )
            )
        )
        notes.append(
            f"pattern_B_msg_per_day_max={b_best[0]} span_min={span_floor}d "
            f"(tp={b_best[1]}, fp={b_best[2]})"
        )
    else:
        notes.append("pattern_B_disabled: no threshold met precision floor")

    if not groups:
        # No pattern reached precision floor — emit an empty recipe with
        # explicit fallback. Tests catch this and force a manual decision.
        notes.append("WARNING: no axes met precision floor; recipe will never match.")

    rc = RecipeCalibration(
        name="lurker_or_observer",
        version="0.2",
        positive_label="lurker",
        groups=tuple(groups),
        strategy=f"precision_floor:{min_precision:.2f} per-pattern, OR-combined",
        tp=0,
        fp=0,
        tn=0,
        fn=0,
        precision=0.0,
        recall=0.0,
        f1=0.0,
        notes=tuple(notes),
    )
    return _populate_metrics(rc, stats, labels)


def search_bot_or_automated_poster(
    stats: list[ActorStats],
    labels: dict[int, ActorLabel],
) -> RecipeCalibration:
    """Operator-locked axes (PLAN §M5, 2026-05-22): no search performed.

    The thresholds were locked because the labeled corpus has only one
    bot example — there is no statistically meaningful sweep. The grid
    just computes the confusion matrix and reports it. If precision or
    recall is low on the labeled set, the operator can revise the axes;
    recipes_grid.py will not auto-tune them.
    """
    groups = (
        AxisGroup(
            axes=(
                AxisThreshold("init_rate", ">=", 0.95),
                AxisThreshold("length_cv", "<=", 0.30),
            )
        ),
    )
    rc = RecipeCalibration(
        name="bot_or_automated_poster",
        version="0.2",
        positive_label="bot",
        groups=groups,
        strategy="operator_locked: init_rate>=0.95 AND length_cv<=0.30",
        tp=0,
        fp=0,
        tn=0,
        fn=0,
        precision=0.0,
        recall=0.0,
        f1=0.0,
        notes=(
            "MATTR also discriminates (SangMata=0.49, human min=0.82) but is "
            "reserved as a future tertiary axis per M5 decision.",
            "inter_msg_cv NOT used: SangMata is event-driven (cv=1.67), so "
            "clockwork-cadence gating would miss this bot class.",
        ),
    )
    return _populate_metrics(rc, stats, labels)


def search_chatty_member(
    stats: list[ActorStats],
    labels: dict[int, ActorLabel],
    *,
    min_precision: float = 0.70,
) -> RecipeCalibration:
    """Single-axis: msg_count >= T. Sweep T to maximize recall at precision floor."""
    # Candidate thresholds = all distinct msg_count values in the cohort.
    candidates = sorted({int(s.msg_count) for s in stats})
    best: tuple[int, int, int] | None = None
    for t in candidates:

        def pred_chatty(s: ActorStats, thr: int = t) -> bool:
            return s.msg_count >= thr

        tp, fp, _, _ = _confusion(stats, labels, "chatty_member", pred_chatty)
        prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        if prec >= min_precision and _picker_prefers(best, tp, fp):
            best = (t, tp, fp)

    # (best updated by _picker_prefers above)
    if best is None:
        # Should not happen with the Rutify labels; defensive.
        rc = RecipeCalibration(
            name="chatty_member",
            version="0.1",
            positive_label="chatty_member",
            groups=(),
            strategy=f"precision_floor:{min_precision:.2f} (FAILED)",
            tp=0,
            fp=0,
            tn=0,
            fn=0,
            precision=0.0,
            recall=0.0,
            f1=0.0,
            notes=("WARNING: no msg_count threshold met the precision floor.",),
        )
        return _populate_metrics(rc, stats, labels)

    groups = (AxisGroup(axes=(AxisThreshold("msg_count", ">=", float(best[0])),)),)
    rc = RecipeCalibration(
        name="chatty_member",
        version="0.1",
        positive_label="chatty_member",
        groups=groups,
        strategy=f"precision_floor:{min_precision:.2f} on msg_count",
        tp=0,
        fp=0,
        tn=0,
        fn=0,
        precision=0.0,
        recall=0.0,
        f1=0.0,
        notes=(f"msg_count_min={best[0]} (tp={best[1]}, fp={best[2]})",),
    )
    return _populate_metrics(rc, stats, labels)


def _populate_metrics(
    rc: RecipeCalibration,
    stats: list[ActorStats],
    labels: dict[int, ActorLabel],
) -> RecipeCalibration:
    """Recompute tp/fp/tn/fn + P/R/F1 with the recipe's final axes."""
    tp, fp, tn, fn = _confusion(stats, labels, rc.positive_label, rc.matches)
    precision, recall, f1 = _prf1(tp, fp, fn)
    return RecipeCalibration(
        name=rc.name,
        version=rc.version,
        positive_label=rc.positive_label,
        groups=rc.groups,
        strategy=rc.strategy,
        tp=tp,
        fp=fp,
        tn=tn,
        fn=fn,
        precision=precision,
        recall=recall,
        f1=f1,
        notes=rc.notes,
    )


def run(
    stats: list[ActorStats],
    labels: dict[int, ActorLabel],
    *,
    min_precision: float = 0.70,
) -> list[RecipeCalibration]:
    """Run all three M5 recipe searches; return them in declaration order."""
    return [
        search_lurker_or_observer(stats, labels, min_precision=min_precision),
        search_bot_or_automated_poster(stats, labels),
        search_chatty_member(stats, labels, min_precision=min_precision),
    ]


def render(rcs: list[RecipeCalibration]) -> str:
    """Compact human-readable summary."""
    lines: list[str] = []
    for rc in rcs:
        lines.append("")
        lines.append(f"=== {rc.name} (v{rc.version}) ===")
        lines.append(f"strategy: {rc.strategy}")
        lines.append(f"positive_label: {rc.positive_label}")
        if rc.groups:
            for i, g in enumerate(rc.groups):
                axes_str = "  AND  ".join(f"{a.feature} {a.op} {a.value}" for a in g.axes)
                lines.append(f"  group[{i}]: {axes_str}")
            if len(rc.groups) > 1:
                lines.append("  (groups OR'd)")
        else:
            lines.append("  groups: (empty)")
        lines.append(f"confusion: tp={rc.tp}  fp={rc.fp}  tn={rc.tn}  fn={rc.fn}")
        lines.append(f"P={rc.precision:.3f}  R={rc.recall:.3f}  F1={rc.f1:.3f}")
        for n in rc.notes:
            lines.append(f"  note: {n}")
    return "\n".join(lines)


__all__ = [
    "AxisGroup",
    "AxisThreshold",
    "RecipeCalibration",
    "render",
    "run",
    "search_bot_or_automated_poster",
    "search_chatty_member",
    "search_lurker_or_observer",
]
