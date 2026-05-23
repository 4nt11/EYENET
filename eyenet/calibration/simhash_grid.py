"""Simhash threshold grid — within/cross author distance distributions + AUC.

Calls the function_word and character_ngram primitives directly (no NATS, no
sensor envelope) on per-actor split-halves. The result is a pair of
distance distributions:

* **within-author** — one Hamming distance per actor (half-A vs half-B),
* **cross-author**  — all-pairs Hamming over half-A vectors across actors.

From those we compute:

* the AUC (one-tailed, lower distance = more likely same author) via the
  exact Mann-Whitney U statistic — no scientific deps required, and small N
  is fine because U is unbiased,
* the threshold sweep over [0, 64] reporting precision / recall / F1,
* the precision-floor operating point (M5 strategy β: precision-first).

Per-primitive output is :class:`PrimitiveGridResult`. The CLI / artifact
serializer consumes a list of these.

--------------------------------------------------------------------------
M5 calibration outcome on Rutify (2026-05-22):

The Rutify corpus is short Spanish chat. Neither simhash primitive can
support precision ≥ 0.70 at any operating point — AUC plateaus at 0.55
(function_word) and 0.68 (char_ngram); the within/cross distance
distributions overlap too much.

Operator decision: **simhash linker is explicitly DISABLED for Spanish**
via ``LinkerThresholds.<comparator>_per_lang["es"] = None``. The long-term
fix is minhash-with-n-gram-shingles, which lands in BEHAVE-TEXT 0.0.2;
until then, Spanish linkage is driven by the recipe layer (interaction
stats) and the planned LLM-Confirmer service.

This module retains full precision-floor + F1-max machinery so the same
grid can be re-run against future corpora and against a future minhash
primitive without code changes.
--------------------------------------------------------------------------
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid5

from eyenet.linker.comparators._distance import hamming64
from eyenet.sensor.primitives.character_ngram_simhash import (
    compute as compute_char_ngram,
)
from eyenet.sensor.primitives.function_word_distribution_top50 import (
    compute as compute_function_word,
)

from .corpus import RutifyMessage, split_halves

_NAMESPACE = UUID("00000000-0000-0000-0000-0000ca11b8a7")
"""Stable UUIDv5 namespace for synthesizing per-message UUIDs in calibration.

The primitive ``compute`` signature expects ``list[tuple[datetime, UUID, str]]``
plus ``bodies: dict[str, str]``. We don't persist these UUIDs; they exist only
to satisfy the primitive contract during a calibration run.
"""


@dataclass(frozen=True)
class HalfHash:
    """One primitive evaluation for one half of one actor's corpus."""

    actor_id: int  # the Telegram sender_id; not a UUID at this layer
    primitive: str  # e.g. "function_word_distribution_top50"
    half: str  # "a" or "b"
    hash_hex: str  # 16-char 64-bit hex string
    language: str | None  # set for function_word; None elsewhere


@dataclass(frozen=True)
class ThresholdRow:
    """One row of the precision/recall sweep."""

    threshold: int
    tp: int
    fp: int
    tn: int
    fn: int
    precision: float
    recall: float
    f1: float


@dataclass(frozen=True)
class PrimitiveGridResult:
    """Calibration outcome for a single primitive (per language slice).

    M5 default strategy is ``precision_floor`` at 0.70 (β path). Two operating
    points are recorded so the artifact carries enough provenance to migrate
    the chosen strategy later without recomputing:

    * ``chosen_*`` — the operating point the Linker will use.
    * ``f1_max_*`` — F1-max baseline (for reporting / regression tracking).
    """

    primitive: str
    language: str | None  # "es" for Spanish-only slice; None = combined
    actors_fired: int
    within_distances: tuple[int, ...]
    cross_distances: tuple[int, ...]
    auc: float
    sweep: tuple[ThresholdRow, ...]
    strategy: str  # "precision_floor:0.70" or "f1_max"
    chosen_threshold: int
    chosen_f1: float
    chosen_precision: float
    chosen_recall: float
    f1_max_threshold: int
    f1_max_f1: float
    f1_max_precision: float
    f1_max_recall: float


@dataclass(frozen=True)
class GridResult:
    """Aggregate grid result across all primitives + language slices."""

    actor_count: int
    half_hashes: tuple[HalfHash, ...]
    per_primitive: tuple[PrimitiveGridResult, ...]
    notes: tuple[str, ...] = field(default_factory=tuple)


# -- helpers ----------------------------------------------------------------


def _to_primitive_corpus(
    messages: list[RutifyMessage],
) -> tuple[list[tuple[datetime, UUID, str]], dict[str, str]]:
    corpus: list[tuple[datetime, UUID, str]] = []
    bodies: dict[str, str] = {}
    for m in messages:
        msg_uuid = uuid5(_NAMESPACE, f"{m.chat_id}:{m.msg_id}:{m.sender_id}")
        ts = datetime.fromtimestamp(m.ts, tz=UTC)
        ref = m.evidence_ref
        corpus.append((ts, msg_uuid, ref))
        bodies[ref] = m.text
    return corpus, bodies


def _language_from_source(source: str | None) -> str | None:
    if not source:
        return None
    _, sep, tail = source.rpartition("#")
    return tail.strip().lower() if sep else None


def _compute_half_hash(
    primitive_name: str,
    messages: list[RutifyMessage],
    actor_id: int,
    half: str,
) -> HalfHash | None:
    corpus, bodies = _to_primitive_corpus(messages)
    if primitive_name == "function_word_distribution_top50":
        obs = compute_function_word(corpus=corpus, bodies=bodies)
    elif primitive_name == "character_ngram_simhash":
        obs = compute_char_ngram(corpus=corpus, bodies=bodies)
    else:
        msg = f"unsupported primitive in calibration grid: {primitive_name!r}"
        raise ValueError(msg)
    if obs is None:
        return None
    lang = _language_from_source(obs.source) if primitive_name.startswith("function_word") else None
    return HalfHash(
        actor_id=actor_id,
        primitive=primitive_name,
        half=half,
        hash_hex=str(obs.value),
        language=lang,
    )


# -- distance distributions -------------------------------------------------


def _within_author_distances(half_hashes: list[HalfHash]) -> list[int]:
    by_actor: dict[int, dict[str, str]] = {}
    for h in half_hashes:
        by_actor.setdefault(h.actor_id, {})[h.half] = h.hash_hex
    out: list[int] = []
    for halves in by_actor.values():
        if "a" in halves and "b" in halves:
            out.append(hamming64(halves["a"], halves["b"]))
    return out


def _cross_author_distances(half_hashes: list[HalfHash]) -> list[int]:
    """All-pairs cross-author distances using half-A only.

    Half-A is the older half. We pair half-A across distinct actors; this
    gives one comparison per unordered actor pair. Using half-A only avoids
    inflating the cross set by factor-of-4 from cross-half pairings.
    """
    a_only: list[tuple[int, str]] = [(h.actor_id, h.hash_hex) for h in half_hashes if h.half == "a"]
    out: list[int] = []
    for i in range(len(a_only)):
        for j in range(i + 1, len(a_only)):
            out.append(hamming64(a_only[i][1], a_only[j][1]))
    return out


# -- AUC + threshold sweep --------------------------------------------------


def mann_whitney_auc(within: list[int], cross: list[int]) -> float:
    """One-tailed AUC: P(within_distance < cross_distance).

    Implemented via the exact Mann-Whitney U statistic with mid-rank ties.
    No scipy / numpy dependency: this is O(n*m) and fine at our scale
    (<100 vs <10_000 pairs).

    Returns a value in ``[0.0, 1.0]``. 0.5 = no discrimination. 1.0 = every
    within-author distance is strictly smaller than every cross-author
    distance.
    """
    if not within or not cross:
        return 0.5
    wins = 0.0
    for w in within:
        for c in cross:
            if w < c:
                wins += 1.0
            elif w == c:
                wins += 0.5
    return wins / (len(within) * len(cross))


def _threshold_sweep(within: list[int], cross: list[int]) -> list[ThresholdRow]:
    """Compute precision/recall/F1 at every integer threshold in [0, 64].

    Convention: a pair is "predicted same-author" when distance ≤ threshold.
    within-author pairs are true positives; cross-author pairs are negatives.
    """
    n_within = len(within)
    n_cross = len(cross)
    if n_within == 0 or n_cross == 0:
        return []
    rows: list[ThresholdRow] = []
    for t in range(0, 65):
        tp = sum(1 for d in within if d <= t)
        fn = n_within - tp
        fp = sum(1 for d in cross if d <= t)
        tn = n_cross - fp
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / n_within
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
        rows.append(
            ThresholdRow(
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


def _pick_f1_max(rows: list[ThresholdRow]) -> ThresholdRow:
    """Return the row with the highest F1; ties broken by tighter threshold."""
    best = rows[0]
    for r in rows[1:]:
        if r.f1 > best.f1 or (r.f1 == best.f1 and r.threshold < best.threshold):
            best = r
    return best


def _pick_precision_floor(rows: list[ThresholdRow], *, min_precision: float) -> ThresholdRow:
    """Return the highest-recall row whose precision ≥ ``min_precision``.

    Strategy used by the M5 simhash calibration (β: precision-first). The
    Linker's job is to emit *high-confidence* proposals; sifting noise is
    the operator's (or a future LLM-confirmer's) job, not theirs.

    If no row meets the floor, returns the row with the highest precision
    seen — a conservative fallback that prefers fewer, stronger proposals
    over none at all.
    """
    eligible = [r for r in rows if r.precision >= min_precision]
    if eligible:
        # Among rows meeting the precision floor, take the loosest threshold
        # (highest recall). Ties on recall broken by tighter threshold.
        best = eligible[0]
        for r in eligible[1:]:
            if r.recall > best.recall or (r.recall == best.recall and r.threshold < best.threshold):
                best = r
        return best
    # No row hits the floor — fall back to the absolute precision-max.
    best = rows[0]
    for r in rows[1:]:
        if r.precision > best.precision or (
            r.precision == best.precision and r.threshold < best.threshold
        ):
            best = r
    return best


# -- main entry point -------------------------------------------------------


DEFAULT_MIN_PRECISION: float = 0.70
"""β: precision-first threshold strategy. Locked by operator decision 2026-05-22.

The Linker emits high-confidence linkage proposals; recall is the future
LLM-Confirmer's job (and the operator's review queue). Lowering this to a
recall-balanced operating point requires an explicit re-calibration.
"""


def run(
    grouped: dict[int, list[RutifyMessage]],
    *,
    primitives: tuple[str, ...] = (
        "function_word_distribution_top50",
        "character_ngram_simhash",
    ),
    language_filter: str | None = "es",
    min_precision: float = DEFAULT_MIN_PRECISION,
) -> GridResult:
    """Run the full simhash calibration grid.

    Args:
      grouped: ``{sender_id: chronologically-sorted-messages}`` from
        :func:`eyenet.calibration.corpus.group_by_sender`.
      primitives: which primitives to evaluate. Default: function_word + char_ngram.
      language_filter: when set, restricts AUC / sweep computation to half-hashes
        whose detected language equals this code. Char_ngram has no
        detected language and inherits the actor's function_word language;
        an actor with no function_word evaluation is excluded from the
        language-filtered char_ngram slice. ``None`` = no filter.

    Returns: a :class:`GridResult` with per-primitive sweeps and chosen
    F1-max thresholds.
    """
    half_hashes: list[HalfHash] = []
    notes: list[str] = []

    for prim in primitives:
        for actor_id, msgs in grouped.items():
            a, b = split_halves(msgs, mode="chronological")
            if not a or not b:
                continue
            ha = _compute_half_hash(prim, a, actor_id, "a")
            hb = _compute_half_hash(prim, b, actor_id, "b")
            if ha is not None:
                half_hashes.append(ha)
            if hb is not None:
                half_hashes.append(hb)

    # Build actor-wide language tag from function_word half-A (the older half).
    actor_lang: dict[int, str] = {}
    for h in half_hashes:
        if h.primitive == "function_word_distribution_top50" and h.half == "a" and h.language:
            actor_lang[h.actor_id] = h.language

    per_prim: list[PrimitiveGridResult] = []
    for prim in primitives:
        prim_hashes = [h for h in half_hashes if h.primitive == prim]
        if language_filter is not None:
            if prim.startswith("function_word"):
                prim_hashes = [h for h in prim_hashes if h.language == language_filter]
            else:
                # char_ngram inherits the actor's function_word language.
                prim_hashes = [
                    h for h in prim_hashes if actor_lang.get(h.actor_id) == language_filter
                ]
        within = _within_author_distances(prim_hashes)
        cross = _cross_author_distances(prim_hashes)
        actors_fired = sum(1 for h in prim_hashes if h.half == "a")
        if not within or not cross:
            notes.append(f"{prim}: insufficient pairs (within={len(within)}, cross={len(cross)})")
            per_prim.append(
                PrimitiveGridResult(
                    primitive=prim,
                    language=language_filter,
                    actors_fired=actors_fired,
                    within_distances=tuple(within),
                    cross_distances=tuple(cross),
                    auc=0.5,
                    sweep=(),
                    strategy=f"precision_floor:{min_precision:.2f}",
                    chosen_threshold=0,
                    chosen_f1=0.0,
                    chosen_precision=0.0,
                    chosen_recall=0.0,
                    f1_max_threshold=0,
                    f1_max_f1=0.0,
                    f1_max_precision=0.0,
                    f1_max_recall=0.0,
                )
            )
            continue
        auc = mann_whitney_auc(within, cross)
        rows = _threshold_sweep(within, cross)
        chosen = _pick_precision_floor(rows, min_precision=min_precision)
        f1_best = _pick_f1_max(rows)
        per_prim.append(
            PrimitiveGridResult(
                primitive=prim,
                language=language_filter,
                actors_fired=actors_fired,
                within_distances=tuple(within),
                cross_distances=tuple(cross),
                auc=round(auc, 4),
                sweep=tuple(rows),
                strategy=f"precision_floor:{min_precision:.2f}",
                chosen_threshold=chosen.threshold,
                chosen_f1=chosen.f1,
                chosen_precision=chosen.precision,
                chosen_recall=chosen.recall,
                f1_max_threshold=f1_best.threshold,
                f1_max_f1=f1_best.f1,
                f1_max_precision=f1_best.precision,
                f1_max_recall=f1_best.recall,
            )
        )

    return GridResult(
        actor_count=len(grouped),
        half_hashes=tuple(half_hashes),
        per_primitive=tuple(per_prim),
        notes=tuple(notes),
    )


def render_grid_result(g: GridResult) -> str:
    """Compact human-readable summary for stdout."""
    lines = [
        f"actors qualifying for split: {g.actor_count}",
        f"half-hashes computed: {len(g.half_hashes)}",
    ]
    for note in g.notes:
        lines.append(f"NOTE: {note}")
    for r in g.per_primitive:
        lang_tag = f"[{r.language}]" if r.language else "[all]"
        lines.append("")
        lines.append(f"=== {r.primitive} {lang_tag} ===")
        lines.append(
            f"actors fired: {r.actors_fired}   "
            f"within pairs: {len(r.within_distances)}   "
            f"cross pairs: {len(r.cross_distances)}"
        )
        if r.within_distances:
            lines.append(
                f"within: min={min(r.within_distances)}  "
                f"p50={sorted(r.within_distances)[len(r.within_distances) // 2]}  "
                f"max={max(r.within_distances)}"
            )
        if r.cross_distances:
            cs = sorted(r.cross_distances)
            lines.append(f"cross:  min={cs[0]}  p50={cs[len(cs) // 2]}  max={cs[-1]}")
        lines.append(f"AUC: {r.auc:.4f}")
        lines.append(
            f"chosen ({r.strategy}) @ t={r.chosen_threshold}:  "
            f"P={r.chosen_precision:.3f}  R={r.chosen_recall:.3f}  F1={r.chosen_f1:.3f}"
        )
        lines.append(
            f"f1-max baseline @ t={r.f1_max_threshold}:  "
            f"P={r.f1_max_precision:.3f}  R={r.f1_max_recall:.3f}  F1={r.f1_max_f1:.3f}"
        )
    return "\n".join(lines)


__all__ = [
    "GridResult",
    "HalfHash",
    "PrimitiveGridResult",
    "ThresholdRow",
    "mann_whitney_auc",
    "render_grid_result",
    "run",
]
