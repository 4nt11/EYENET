"""Verifier threshold grid (M8) — score-higher-is-better mirror of simhash_grid.

Computes per-verifier within-author and cross-author score distributions
over the Rutify corpus, plus AUC and a precision-floor threshold sweep.

Differences from ``simhash_grid`` (intentional — same shape, inverse domain):

* Scores live in ``[0.0, 1.0]`` with **higher = more likely same author**.
* "Predict SAME" iff ``score >= threshold`` (vs. simhash ``distance <= t``).
* AUC computed as ``P(within_score > cross_score)`` (inverse direction).
* Sweep walks 0..100 in 1/100 increments (101 rows) — finer than simhash's
  integer Hamming range.

Within-pair shape: per sender, split_halves(...) → (half_a, half_b) of
message bodies → one score per verifier.

Cross-pair shape: random sampling across senders, capped at
``5x |within_pairs|`` to keep the grid bounded. Sampling uses a fixed RNG
seed for reproducibility.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from eyenet.verifier.verifiers import REGISTRY, Verifier, default_registry

from .corpus import RutifyMessage, group_by_sender, split_halves


@dataclass(frozen=True)
class VerifierThresholdRow:
    threshold: float  # score floor in [0.0, 1.0], two-decimal step
    tp: int
    fp: int
    tn: int
    fn: int
    precision: float
    recall: float
    f1: float


@dataclass(frozen=True)
class VerifierGridResult:
    """One verifier's calibration outcome (per language slice).

    Mirrors :class:`PrimitiveGridResult` from ``simhash_grid`` but for
    score-higher-is-better metrics.
    """

    verifier: str
    language: str | None
    actors_evaluated: int
    within_scores: tuple[float, ...]
    cross_scores: tuple[float, ...]
    auc: float
    sweep: tuple[VerifierThresholdRow, ...]
    strategy: str  # e.g. "precision_floor:0.70"
    chosen_threshold: float
    chosen_f1: float
    chosen_precision: float
    chosen_recall: float
    f1_max_threshold: float
    f1_max_f1: float
    f1_max_precision: float
    f1_max_recall: float


@dataclass(frozen=True)
class VerifierGrid:
    """Aggregate grid across all verifiers."""

    actor_count: int
    per_verifier: tuple[VerifierGridResult, ...]
    notes: tuple[str, ...] = field(default_factory=tuple)


def mann_whitney_auc_higher_better(within: list[float], cross: list[float]) -> float:
    """AUC for score-higher-is-better: ``P(within_score > cross_score)``.

    Symmetric inverse of :func:`simhash_grid.mann_whitney_auc`. Returns
    0.5 on empty input; 1.0 = perfect separation.
    """
    if not within or not cross:
        return 0.5
    wins = 0.0
    for w in within:
        for c in cross:
            if w > c:
                wins += 1.0
            elif w == c:
                wins += 0.5
    return wins / (len(within) * len(cross))


def _threshold_sweep(
    within: list[float], cross: list[float], *, step: float = 0.01
) -> list[VerifierThresholdRow]:
    """Sweep score floor over [0, 1] at ``step`` granularity.

    Predict SAME iff score >= threshold. within = positives, cross =
    negatives. Returns 101 rows by default (step=0.01).
    """
    n_within = len(within)
    n_cross = len(cross)
    if n_within == 0 or n_cross == 0:
        return []
    rows: list[VerifierThresholdRow] = []
    n_steps = round(1.0 / step) + 1
    for i in range(n_steps):
        t = round(i * step, 4)
        tp = sum(1 for s in within if s >= t)
        fn = n_within - tp
        fp = sum(1 for s in cross if s >= t)
        tn = n_cross - fp
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / n_within
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
        rows.append(
            VerifierThresholdRow(
                threshold=t,
                tp=tp,
                fp=fp,
                tn=tn,
                fn=fn,
                precision=round(precision, 4),
                recall=round(recall, 4),
                f1=round(f1, 4),
            )
        )
    return rows


def _pick_f1_max(rows: list[VerifierThresholdRow]) -> VerifierThresholdRow:
    """Highest F1; ties broken by higher threshold (more selective)."""
    best = rows[0]
    for r in rows[1:]:
        if r.f1 > best.f1 or (r.f1 == best.f1 and r.threshold > best.threshold):
            best = r
    return best


def _pick_precision_floor(
    rows: list[VerifierThresholdRow], *, min_precision: float
) -> VerifierThresholdRow:
    """Highest-recall row with precision >= floor; falls back to precision-max."""
    eligible = [r for r in rows if r.precision >= min_precision]
    if eligible:
        # Highest recall among eligible; ties on recall broken by LOWER
        # threshold (more inclusive — symmetric to simhash's "tighter
        # threshold = lower distance" tiebreaker).
        best = eligible[0]
        for r in eligible[1:]:
            if r.recall > best.recall or (r.recall == best.recall and r.threshold < best.threshold):
                best = r
        return best
    best = rows[0]
    for r in rows[1:]:
        if r.precision > best.precision or (
            r.precision == best.precision and r.threshold > best.threshold
        ):
            best = r
    return best


DEFAULT_MIN_PRECISION: float = 0.70
"""Same operator policy as the simhash grid (PLAN §M5). Tighten or loosen by
recalibration only — high-confidence proposals are the Verifier's job.
"""


def _bodies(msgs: list[RutifyMessage]) -> list[str]:
    return [m.text for m in msgs]


def _sample_diff_pairs(
    actors: list[int],
    sender_to_half_a: dict[int, list[str]],
    sender_to_half_b: dict[int, list[str]],
    *,
    target_pairs: int,
    seed: int,
) -> list[tuple[list[str], list[str]]]:
    """Random cross-sender pairs. Drawn without replacement on the (sa, sb) key."""
    rng = random.Random(seed)  # noqa: S311  # nosec B311 — calibration sampling, not crypto
    out: list[tuple[list[str], list[str]]] = []
    seen: set[tuple[int, int]] = set()
    attempts = 0
    max_attempts = target_pairs * 20
    while len(out) < target_pairs and attempts < max_attempts:
        attempts += 1
        sa, sb = rng.sample(actors, 2)
        key = (sa, sb) if sa < sb else (sb, sa)
        if key in seen:
            continue
        seen.add(key)
        out.append((sender_to_half_a[sa], sender_to_half_b[sb]))
    return out


_MIN_ACTORS_FOR_GRID = 2
"""Need at least two qualifying actors to form even one within/cross comparison."""


def run(  # noqa: PLR0912 — calibration grid intentionally branches wide on impostor/registry options
    messages: list[RutifyMessage],
    *,
    min_messages: int = 60,
    language: str | None = "es",
    verifiers: tuple[Verifier, ...] | None = None,
    impostor_corpora: list[list[str]] | None = None,
    diff_pair_multiplier: int = 5,
    rng_seed: int = 20260524,
    min_precision: float = DEFAULT_MIN_PRECISION,
) -> VerifierGrid:
    """Run the verifier grid across the labeled corpus.

    Args:
        messages: full corpus (already sorted across senders).
        min_messages: minimum messages per sender to qualify.
        language: BCP-47 code for the AUC slice. ``None`` ⇒ language-blind.
        verifiers: override REGISTRY (tests pass a tuple of one verifier).
            When None, :func:`default_registry` is rebuilt with
            ``impostor_corpora`` if provided.
        impostor_corpora: external impostor pool; passed to GeneralImpostors.
            Defaults to the cross-sender pool synthesized from ``messages``.
        diff_pair_multiplier: cross-sender pair count = mult x within count.
        rng_seed: random seed for impostor + diff-pair sampling.
        min_precision: precision floor for the strategy pick.
    """
    grouped = group_by_sender(messages, min_messages=min_messages)
    if len(grouped) < _MIN_ACTORS_FOR_GRID:
        return VerifierGrid(actor_count=len(grouped), per_verifier=())

    sender_to_half_a: dict[int, list[str]] = {}
    sender_to_half_b: dict[int, list[str]] = {}
    for sender_id, msgs in grouped.items():
        a, b = split_halves(msgs, mode="chronological")
        if not a or not b:
            continue
        sender_to_half_a[sender_id] = _bodies(a)
        sender_to_half_b[sender_id] = _bodies(b)

    qualifying_actors = sorted(sender_to_half_a.keys())
    if len(qualifying_actors) < _MIN_ACTORS_FOR_GRID:
        return VerifierGrid(actor_count=len(grouped), per_verifier=())

    # Build the impostor pool from cross-sender HALF-A corpora when an
    # external one is not provided. Cap to avoid pathological pool sizes.
    if impostor_corpora is None:
        rng = random.Random(rng_seed)  # noqa: S311  # nosec B311 — calibration sampling, not crypto
        pool_cap = min(50, len(qualifying_actors))
        impostor_actors = rng.sample(qualifying_actors, pool_cap)
        impostor_corpora = [sender_to_half_a[a] for a in impostor_actors]

    if verifiers is None:
        verifiers = default_registry(impostor_corpora=impostor_corpora)
        if not verifiers:
            verifiers = REGISTRY

    # SAME pairs: half_a vs half_b for each qualifying actor.
    within_pairs: list[tuple[list[str], list[str]]] = [
        (sender_to_half_a[a], sender_to_half_b[a]) for a in qualifying_actors
    ]
    # DIFF pairs: random cross-sender (capped).
    target_diff = max(diff_pair_multiplier * len(within_pairs), len(within_pairs))
    cross_pairs = _sample_diff_pairs(
        qualifying_actors,
        sender_to_half_a,
        sender_to_half_b,
        target_pairs=target_diff,
        seed=rng_seed + 1,
    )

    per_verifier: list[VerifierGridResult] = []
    strategy_label = f"precision_floor:{min_precision:.2f}"

    for verifier in verifiers:
        within_scores: list[float] = []
        for ca, cb in within_pairs:
            r = verifier.verify(ca, cb, language=language)
            if r.skipped or r.confidence == 0.0:
                continue
            within_scores.append(r.score)
        cross_scores: list[float] = []
        for ca, cb in cross_pairs:
            r = verifier.verify(ca, cb, language=language)
            if r.skipped or r.confidence == 0.0:
                continue
            cross_scores.append(r.score)

        auc = mann_whitney_auc_higher_better(within_scores, cross_scores)
        sweep = _threshold_sweep(within_scores, cross_scores)
        if sweep:
            chosen = _pick_precision_floor(sweep, min_precision=min_precision)
            f1_max = _pick_f1_max(sweep)
        else:
            empty = VerifierThresholdRow(
                threshold=0.0,
                tp=0,
                fp=0,
                tn=0,
                fn=0,
                precision=0.0,
                recall=0.0,
                f1=0.0,
            )
            chosen = empty
            f1_max = empty

        per_verifier.append(
            VerifierGridResult(
                verifier=verifier.name,
                language=language,
                actors_evaluated=len(within_scores),
                within_scores=tuple(within_scores),
                cross_scores=tuple(cross_scores),
                auc=auc,
                sweep=tuple(sweep),
                strategy=strategy_label,
                chosen_threshold=chosen.threshold,
                chosen_f1=chosen.f1,
                chosen_precision=chosen.precision,
                chosen_recall=chosen.recall,
                f1_max_threshold=f1_max.threshold,
                f1_max_f1=f1_max.f1,
                f1_max_precision=f1_max.precision,
                f1_max_recall=f1_max.recall,
            )
        )

    return VerifierGrid(
        actor_count=len(qualifying_actors),
        per_verifier=tuple(per_verifier),
    )


__all__ = [
    "DEFAULT_MIN_PRECISION",
    "VerifierGrid",
    "VerifierGridResult",
    "VerifierThresholdRow",
    "mann_whitney_auc_higher_better",
    "run",
]
