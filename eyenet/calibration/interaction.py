"""Per-actor interaction & lexical statistics for recipe calibration.

These features feed the recipe threshold search (Phase 4). They are
language-agnostic numeric scalars: initiation rate, reply rate, mention
rate, message-length statistics, inter-message-gap statistics, and MATTR
(moving-average type-token ratio — lexical diversity).

All stats are computed from raw ``RutifyMessage`` lists; the MATTR primitive
is invoked directly (no NATS, no Observation envelope) the same way the
simhash grid does it.

Output is a list of :class:`ActorStats`, one per qualifying actor, plus
:func:`write_csv` to dump to disk. The CSV is committed (no message bodies,
no usernames — pseudonymous sender IDs only).
"""

from __future__ import annotations

import csv
import statistics
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid5

from eyenet.sensor.primitives.mattr import compute as compute_mattr

from .corpus import RutifyMessage

_NAMESPACE = UUID("00000000-0000-0000-0000-0000ca11b8a7")
_MIN_VALUES_FOR_CV: int = 2


@dataclass(frozen=True)
class ActorStats:
    """Per-actor numeric feature vector for recipe calibration.

    Field semantics:

    * ``msg_count``       — non-empty text messages.
    * ``corpus_span_days``— ``(last_ts - first_ts) / 86400``; 0 if singleton.
    * ``msg_per_day``     — ``msg_count / max(corpus_span_days, 1)``.
    * ``init_rate``       — fraction of msgs with no reply target. Matches
                            the ``interaction.conversation_initiation_rate``
                            primitive exactly so calibrated thresholds carry
                            over to the recipe layer. Forwards count AS
                            initiations (they begin a new conversation).
    * ``reply_rate``      — ``1 - init_rate``.
    * ``mention_rate``    — fraction of msgs that mention another user.
    * ``mean_msg_chars``  — mean of ``len(text)`` (Unicode codepoints).
    * ``median_msg_chars``— median of same.
    * ``length_cv``       — stddev / mean of msg lengths. ~0 = bot-like
                            uniformity, larger = human variance.
    * ``inter_msg_p50``   — median gap (seconds) between consecutive msgs.
    * ``inter_msg_cv``    — gap coefficient of variation. Near-zero =
                            bot-like clockwork posting cadence.
    * ``mattr``           — MATTR over full per-actor corpus, or NaN sentinel
                            (-1.0) if the primitive declined (under
                            ``MIN_TOKENS=100``).
    """

    sender_id: int
    msg_count: int
    corpus_span_days: float
    msg_per_day: float
    init_rate: float
    reply_rate: float
    mention_rate: float
    mean_msg_chars: float
    median_msg_chars: float
    length_cv: float
    inter_msg_p50: float
    inter_msg_cv: float
    mattr: float


def _coefficient_of_variation(values: list[float]) -> float:
    """Stddev divided by mean; 0.0 for degenerate inputs.

    Returns 0.0 when there is less than two values OR the mean is 0.0
    (preferring "degenerate -> zero" over raising; calibration prefers
    a numerical signal over a missing one).
    """
    if len(values) < _MIN_VALUES_FOR_CV:
        return 0.0
    mean = statistics.fmean(values)
    if mean == 0.0:
        return 0.0
    sd = statistics.pstdev(values)
    return sd / mean


def _compute_mattr_for_actor(messages: list[RutifyMessage]) -> float:
    """Run the MATTR primitive on the full per-actor corpus."""
    corpus: list[tuple[datetime, UUID, str]] = []
    bodies: dict[str, str] = {}
    for m in messages:
        ts = datetime.fromtimestamp(m.ts, tz=UTC)
        msg_uuid = uuid5(_NAMESPACE, f"{m.chat_id}:{m.msg_id}:{m.sender_id}")
        corpus.append((ts, msg_uuid, m.evidence_ref))
        bodies[m.evidence_ref] = m.text
    obs = compute_mattr(corpus=corpus, bodies=bodies)
    if obs is None:
        return -1.0  # sentinel: primitive declined (insufficient tokens)
    return float(obs.value)


def compute_actor_stats(messages: list[RutifyMessage]) -> ActorStats:
    """Compute the feature vector for one actor.

    ``messages`` MUST be chronologically sorted (``group_by_sender`` does
    this). Caller must guarantee non-empty input.
    """
    if not messages:
        msg = "compute_actor_stats requires at least one message"
        raise ValueError(msg)

    sender_id = messages[0].sender_id
    n = len(messages)
    first_ts = messages[0].ts
    last_ts = messages[-1].ts
    span_days = max((last_ts - first_ts) / 86400.0, 0.0)

    init_count = sum(1 for m in messages if m.reply_to_msg_id is None)
    mention_count = sum(1 for m in messages if m.mentions)

    lengths = [float(len(m.text)) for m in messages]
    mean_len = statistics.fmean(lengths)
    median_len = statistics.median(lengths)
    length_cv = _coefficient_of_variation(lengths)

    gaps: list[float] = []
    for i in range(1, n):
        delta = messages[i].ts - messages[i - 1].ts
        if delta > 0:
            gaps.append(delta)

    inter_msg_p50 = float(statistics.median(gaps)) if gaps else 0.0
    inter_msg_cv = _coefficient_of_variation(gaps)

    init_rate = init_count / n
    reply_rate = 1.0 - init_rate
    mention_rate = mention_count / n
    msg_per_day = n / max(span_days, 1.0)

    mattr = _compute_mattr_for_actor(messages)

    return ActorStats(
        sender_id=sender_id,
        msg_count=n,
        corpus_span_days=round(span_days, 4),
        msg_per_day=round(msg_per_day, 4),
        init_rate=round(init_rate, 4),
        reply_rate=round(reply_rate, 4),
        mention_rate=round(mention_rate, 4),
        mean_msg_chars=round(mean_len, 2),
        median_msg_chars=round(median_len, 2),
        length_cv=round(length_cv, 4),
        inter_msg_p50=round(inter_msg_p50, 2),
        inter_msg_cv=round(inter_msg_cv, 4),
        mattr=round(mattr, 6),
    )


def compute_all(grouped: dict[int, list[RutifyMessage]]) -> list[ActorStats]:
    """Compute :class:`ActorStats` for every actor in ``grouped``."""
    rows = [compute_actor_stats(msgs) for msgs in grouped.values()]
    # Stable order: largest corpus first — helpful for label-helper triage.
    rows.sort(key=lambda r: r.msg_count, reverse=True)
    return rows


def write_csv(rows: list[ActorStats], path: Path) -> None:
    """Write per-actor stats to a CSV file (committed fixture).

    Schema: one row per actor. No message bodies, no usernames — only the
    pseudonymous ``sender_id`` and the derived numeric stats.
    """
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(asdict(rows[0]).keys())
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(asdict(r))


__all__ = [
    "ActorStats",
    "compute_actor_stats",
    "compute_all",
    "write_csv",
]
