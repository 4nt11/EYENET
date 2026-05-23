"""Unit tests for :mod:`eyenet.calibration.interaction`."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from eyenet.calibration.corpus import RutifyMessage
from eyenet.calibration.interaction import (
    _coefficient_of_variation,
    compute_actor_stats,
    compute_all,
    write_csv,
)


def _msg(
    msg_id: int,
    ts: float,
    text: str = "hello there",
    reply_to: int | None = None,
    mentions: tuple[str, ...] = (),
    fwd: int | None = None,
) -> RutifyMessage:
    return RutifyMessage(
        chat_id=1,
        msg_id=msg_id,
        sender_id=42,
        ts=ts,
        text=text,
        reply_to_msg_id=reply_to,
        forwarded_from_id=fwd,
        mentions=mentions,
    )


@pytest.mark.unit
def test_coefficient_of_variation_zero_for_constant_values() -> None:
    assert _coefficient_of_variation([5.0, 5.0, 5.0]) == 0.0


@pytest.mark.unit
def test_coefficient_of_variation_zero_for_singleton() -> None:
    assert _coefficient_of_variation([7.0]) == 0.0


@pytest.mark.unit
def test_coefficient_of_variation_handles_zero_mean() -> None:
    assert _coefficient_of_variation([0.0, 0.0]) == 0.0


@pytest.mark.unit
def test_coefficient_of_variation_increases_with_spread() -> None:
    low = _coefficient_of_variation([10.0, 11.0, 12.0])
    high = _coefficient_of_variation([1.0, 10.0, 100.0])
    assert high > low


@pytest.mark.unit
def test_compute_actor_stats_empty_raises() -> None:
    with pytest.raises(ValueError, match="requires at least one"):
        compute_actor_stats([])


@pytest.mark.unit
def test_init_rate_all_initiations() -> None:
    msgs = [_msg(i, float(i)) for i in range(10)]
    stats = compute_actor_stats(msgs)
    assert stats.init_rate == pytest.approx(1.0)
    assert stats.reply_rate == pytest.approx(0.0)


@pytest.mark.unit
def test_init_rate_all_replies() -> None:
    msgs = [_msg(i, float(i), reply_to=100) for i in range(10)]
    stats = compute_actor_stats(msgs)
    assert stats.init_rate == pytest.approx(0.0)
    assert stats.reply_rate == pytest.approx(1.0)


@pytest.mark.unit
def test_forwarded_messages_count_as_initiations() -> None:
    # Forwards: counted as initiations per the conversation_initiation_rate
    # primitive's definition (reply_to_msg_id IS NULL → initiation).
    msgs = [_msg(i, float(i), fwd=999) for i in range(5)]
    stats = compute_actor_stats(msgs)
    assert stats.init_rate == pytest.approx(1.0)


@pytest.mark.unit
def test_mention_rate() -> None:
    msgs = [
        _msg(0, 0.0, mentions=("alice",)),
        _msg(1, 1.0, mentions=()),
        _msg(2, 2.0, mentions=("bob", "carol")),
        _msg(3, 3.0, mentions=()),
    ]
    stats = compute_actor_stats(msgs)
    assert stats.mention_rate == pytest.approx(0.5)


@pytest.mark.unit
def test_length_stats_constant_text_zero_cv() -> None:
    msgs = [_msg(i, float(i), text="aaaa") for i in range(5)]
    stats = compute_actor_stats(msgs)
    assert stats.mean_msg_chars == pytest.approx(4.0)
    assert stats.median_msg_chars == pytest.approx(4.0)
    assert stats.length_cv == 0.0


@pytest.mark.unit
def test_inter_msg_gap_uniform_cadence_has_low_cv() -> None:
    # Bot-like: every 60s.
    msgs = [_msg(i, float(i * 60)) for i in range(20)]
    stats = compute_actor_stats(msgs)
    assert stats.inter_msg_p50 == pytest.approx(60.0)
    assert stats.inter_msg_cv == pytest.approx(0.0)


@pytest.mark.unit
def test_inter_msg_gap_irregular_cadence_has_higher_cv() -> None:
    # Human-like: bursty.
    ts = [0, 1, 2, 1000, 1001, 5000]
    msgs = [_msg(i, float(t)) for i, t in enumerate(ts)]
    stats = compute_actor_stats(msgs)
    assert stats.inter_msg_cv > 0.5


@pytest.mark.unit
def test_msg_per_day_uses_span_when_long() -> None:
    # Two messages 2 days apart → msg_per_day = 2/2 = 1.0
    msgs = [_msg(0, 0.0), _msg(1, 2 * 86400.0)]
    stats = compute_actor_stats(msgs)
    assert stats.corpus_span_days == pytest.approx(2.0)
    assert stats.msg_per_day == pytest.approx(1.0)


@pytest.mark.unit
def test_msg_per_day_caps_when_span_short() -> None:
    # 10 messages in 1 second → cap at "per day" using max(span, 1.0)
    msgs = [_msg(i, float(i) * 0.1) for i in range(10)]
    stats = compute_actor_stats(msgs)
    # Span is ~1 sec → max(span_days, 1.0) = 1.0 → msg_per_day = 10.0
    assert stats.msg_per_day == pytest.approx(10.0)


@pytest.mark.unit
def test_mattr_returns_sentinel_when_primitive_declines() -> None:
    # Too few tokens for MATTR (MIN_TOKENS=100). Primitive returns None →
    # interaction.compute returns -1.0 sentinel.
    msgs = [_msg(i, float(i), text="hi") for i in range(20)]
    stats = compute_actor_stats(msgs)
    assert stats.mattr == -1.0


@pytest.mark.unit
def test_compute_all_sorts_by_msg_count_desc() -> None:
    grouped = {
        1: [_msg(i, float(i)) for i in range(3)],
        2: [_msg(i, float(i)) for i in range(10)],
        3: [_msg(i, float(i)) for i in range(5)],
    }
    # patch sender_id on each list to match the dict key
    grouped = {
        k: [
            RutifyMessage(
                chat_id=m.chat_id,
                msg_id=m.msg_id,
                sender_id=k,
                ts=m.ts,
                text=m.text,
                reply_to_msg_id=m.reply_to_msg_id,
                forwarded_from_id=m.forwarded_from_id,
                mentions=m.mentions,
            )
            for m in v
        ]
        for k, v in grouped.items()
    }
    rows = compute_all(grouped)
    assert [r.sender_id for r in rows] == [2, 3, 1]


@pytest.mark.unit
def test_write_csv_round_trip(tmp_path: Path) -> None:
    msgs = [_msg(i, float(i)) for i in range(5)]
    stats = [compute_actor_stats(msgs)]
    out = tmp_path / "stats.csv"
    write_csv(stats, out)
    with out.open() as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
    assert len(rows) == 1
    assert int(rows[0]["sender_id"]) == 42
    assert int(rows[0]["msg_count"]) == 5


@pytest.mark.unit
def test_write_csv_empty(tmp_path: Path) -> None:
    out = tmp_path / "empty.csv"
    write_csv([], out)
    assert out.read_text() == ""
