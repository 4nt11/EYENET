"""Rutify corpus loader — JSONL ingest + per-actor grouping + split-halves.

Pure data layer. No NATS, no sensor calls, no profile shape. The simhash grid
in :mod:`eyenet.calibration.simhash_grid` is the only consumer that bridges
this to primitive computation.

JSONL row shapes (from the operator-supplied dump):

* ``{"type": "chat_header", "chat_id": …, "title": …, …}`` — header row per
  chat; skipped by this loader.
* ``{"type": "message", "chat_id": …, "msg_id": …, "sender_id": …, "ts": …,
  "text": …, "reply_to_msg_id": …, "edited_ts": …, "media_type": …,
  "forwarded_from_id": …, "mentions": […], "v": 1}`` — single message.

Channel-broadcast senders (negative ``sender_id``s like
``-1003020464935``) are excluded by default — they are not authors.
"""

from __future__ import annotations

import json
import statistics
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

CHANNEL_BROADCAST_SENDER_FLOOR: int = 0
"""Sender IDs at or below this value are treated as channel-broadcast accounts.

Telegram channel broadcast IDs are negative (e.g. ``-1003020464935``). They
are not human authors and must not enter calibration.
"""

# Per-half token gates mirroring the primitives' own MIN_TOKENS values.
# Used by the budget report to count how many actors *will* fire each
# primitive on both halves of the chronological split. Keep in sync if the
# primitive thresholds change.
_FUNCTION_WORD_MIN_TOKENS_PER_HALF: int = 500
_CHAR_NGRAM_MIN_TOKENS_PER_HALF: int = 200
_MIN_MESSAGES_FOR_SPLIT: int = 2


@dataclass(frozen=True)
class RutifyMessage:
    """One message row from the Rutify JSONL dump.

    ``ts`` is a UNIX timestamp (float seconds). ``text`` is the raw message
    body; empty / whitespace-only bodies are filtered upstream by
    :func:`group_by_sender`.
    """

    chat_id: int
    msg_id: int
    sender_id: int
    ts: float
    text: str
    reply_to_msg_id: int | None
    forwarded_from_id: int | None
    mentions: tuple[str, ...]

    @property
    def evidence_ref(self) -> str:
        """Stable per-message identifier for primitive ``bodies`` dicts.

        Matches the EYENET convention for evidence_ref in the calibration
        path: ``rutify:{chat_id}:{msg_id}``. Not persisted; the calibration
        artifact never carries message bodies.
        """
        return f"rutify:{self.chat_id}:{self.msg_id}"


def iter_messages(path: Path) -> Iterator[RutifyMessage]:
    """Stream messages from the Rutify JSONL dump.

    Skips ``chat_header`` rows. Skips messages with no ``text`` field (e.g.
    media-only posts). Yields one :class:`RutifyMessage` per text-bearing row.

    Raises :class:`ValueError` on malformed JSON rows (loud-fail; the corpus
    is operator-curated so a parse error indicates corruption, not noise).
    """
    with path.open("r", encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                row: dict[str, object] = json.loads(line)
            except json.JSONDecodeError as exc:
                msg = f"corpus parse error at line {lineno}: {exc}"
                raise ValueError(msg) from exc

            if row.get("type") != "message":
                continue

            text = row.get("text")
            if not isinstance(text, str) or not text.strip():
                continue

            sender_id = row.get("sender_id")
            chat_id = row.get("chat_id")
            msg_id = row.get("msg_id")
            ts = row.get("ts")
            if (
                not isinstance(sender_id, int)
                or not isinstance(chat_id, int)
                or not isinstance(msg_id, int)
                or not isinstance(ts, int | float)
            ):
                continue

            reply_to = row.get("reply_to_msg_id")
            fwd_from = row.get("forwarded_from_id")
            mentions_raw = row.get("mentions")
            mentions = (
                tuple(m for m in mentions_raw if isinstance(m, str))
                if isinstance(mentions_raw, list)
                else ()
            )

            yield RutifyMessage(
                chat_id=chat_id,
                msg_id=msg_id,
                sender_id=sender_id,
                ts=float(ts),
                text=text,
                reply_to_msg_id=reply_to if isinstance(reply_to, int) else None,
                forwarded_from_id=fwd_from if isinstance(fwd_from, int) else None,
                mentions=mentions,
            )


def group_by_sender(
    messages: Iterable[RutifyMessage],
    *,
    min_messages: int = 50,
    exclude_channel_broadcasts: bool = True,
) -> dict[int, list[RutifyMessage]]:
    """Group text messages by sender, filter, and sort chronologically.

    Returns ``{sender_id: [msg, …]}`` where each list is sorted ascending by
    ``ts``. Senders with fewer than ``min_messages`` text messages are
    dropped. When ``exclude_channel_broadcasts`` is True (default), senders
    with negative IDs are also dropped.
    """
    buckets: dict[int, list[RutifyMessage]] = {}
    for m in messages:
        if exclude_channel_broadcasts and m.sender_id <= CHANNEL_BROADCAST_SENDER_FLOOR:
            continue
        buckets.setdefault(m.sender_id, []).append(m)

    qualified: dict[int, list[RutifyMessage]] = {}
    for sender_id, msgs in buckets.items():
        if len(msgs) < min_messages:
            continue
        msgs.sort(key=lambda x: (x.ts, x.msg_id))
        qualified[sender_id] = msgs
    return qualified


def split_halves(
    messages: list[RutifyMessage],
    *,
    mode: str = "chronological",
) -> tuple[list[RutifyMessage], list[RutifyMessage]]:
    """Split a per-sender list into two halves for within-author calibration.

    Modes:

    * ``"chronological"`` (default) — first half = oldest 50%, second half =
      newest 50%. Catches author drift over time; the harder, more honest
      problem.
    * ``"interleaved"`` — even indices vs. odd indices. Useful as a variance
      estimator (drift-free baseline) for sanity-checking simhash signal.

    Caller must pre-sort by ts (``group_by_sender`` does this).
    """
    n = len(messages)
    if n < _MIN_MESSAGES_FOR_SPLIT:
        return ([], [])
    if mode == "chronological":
        mid = n // 2
        return messages[:mid], messages[mid:]
    if mode == "interleaved":
        return messages[0::2], messages[1::2]
    msg = f"unknown split mode: {mode!r}"
    raise ValueError(msg)


def token_count(text: str) -> int:
    """Whitespace-delimited token count — fast, language-agnostic.

    Matches the primitive's notion of "tokens" closely enough for budget
    estimation; precise counting happens inside the primitive itself.
    """
    return len(text.split())


@dataclass(frozen=True)
class TokenBudgetReport:
    """Summary of per-actor token availability after splitting.

    Emitted by :func:`token_budget_report` and used by the calibration CLI
    to decide whether the chosen ``min_messages`` will let the primitives'
    ``MIN_TOKENS`` gates fire on enough actors.
    """

    actor_count: int
    half_token_counts: tuple[int, ...]
    p10: int
    p50: int
    p90: int
    actors_above_500_per_half: int  # function_word MIN_TOKENS
    actors_above_200_per_half: int  # char_ngram MIN_TOKENS

    def render(self) -> str:
        lines = [
            f"actors: {self.actor_count}",
            f"tokens/half: p10={self.p10}  p50={self.p50}  p90={self.p90}",
            f"actors with ≥500 tokens in BOTH halves (function_word eligible): "
            f"{self.actors_above_500_per_half}",
            f"actors with ≥200 tokens in BOTH halves (char_ngram eligible):    "
            f"{self.actors_above_200_per_half}",
        ]
        return "\n".join(lines)


def token_budget_report(
    grouped: dict[int, list[RutifyMessage]],
    *,
    mode: str = "chronological",
) -> TokenBudgetReport:
    """Compute the per-half token distribution for budget planning.

    For each qualifying actor, split into halves and count tokens per half.
    Report the *minimum* of the two halves per actor (the bottleneck for
    within-author distance calibration — both halves must fire the primitive).
    """
    min_half_tokens: list[int] = []
    fw_eligible = 0
    cg_eligible = 0
    for msgs in grouped.values():
        a, b = split_halves(msgs, mode=mode)
        ta = sum(token_count(m.text) for m in a)
        tb = sum(token_count(m.text) for m in b)
        worst = min(ta, tb)
        min_half_tokens.append(worst)
        if ta >= _FUNCTION_WORD_MIN_TOKENS_PER_HALF and tb >= _FUNCTION_WORD_MIN_TOKENS_PER_HALF:
            fw_eligible += 1
        if ta >= _CHAR_NGRAM_MIN_TOKENS_PER_HALF and tb >= _CHAR_NGRAM_MIN_TOKENS_PER_HALF:
            cg_eligible += 1

    if not min_half_tokens:
        return TokenBudgetReport(
            actor_count=0,
            half_token_counts=(),
            p10=0,
            p50=0,
            p90=0,
            actors_above_500_per_half=0,
            actors_above_200_per_half=0,
        )

    sorted_counts = sorted(min_half_tokens)
    return TokenBudgetReport(
        actor_count=len(grouped),
        half_token_counts=tuple(sorted_counts),
        p10=_percentile(sorted_counts, 10),
        p50=int(statistics.median(sorted_counts)),
        p90=_percentile(sorted_counts, 90),
        actors_above_500_per_half=fw_eligible,
        actors_above_200_per_half=cg_eligible,
    )


def _percentile(sorted_vals: list[int], pct: int) -> int:
    if not sorted_vals:
        return 0
    k = max(0, min(len(sorted_vals) - 1, (pct * (len(sorted_vals) - 1)) // 100))
    return sorted_vals[k]


__all__ = [
    "CHANNEL_BROADCAST_SENDER_FLOOR",
    "RutifyMessage",
    "TokenBudgetReport",
    "group_by_sender",
    "iter_messages",
    "split_halves",
    "token_budget_report",
    "token_count",
]
