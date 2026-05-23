"""Unit tests for :mod:`eyenet.calibration.corpus`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eyenet.calibration.corpus import (
    RutifyMessage,
    group_by_sender,
    iter_messages,
    split_halves,
    token_budget_report,
    token_count,
)


def _make_corpus(rows: list[dict[str, object]], tmp: Path) -> Path:
    out = tmp / "corpus.jsonl"
    with out.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    return out


def _msg(
    sender_id: int,
    msg_id: int,
    ts: float,
    text: str = "hola que tal",
    reply_to: int | None = None,
    chat_id: int = 1,
) -> dict[str, object]:
    return {
        "type": "message",
        "chat_id": chat_id,
        "msg_id": msg_id,
        "sender_id": sender_id,
        "ts": ts,
        "text": text,
        "reply_to_msg_id": reply_to,
        "forwarded_from_id": None,
        "mentions": [],
        "v": 1,
    }


@pytest.mark.unit
def test_iter_messages_skips_chat_header(tmp_path: Path) -> None:
    corpus = _make_corpus(
        [
            {"type": "chat_header", "chat_id": 1, "title": "x"},
            _msg(1, 100, 1000.0, "first"),
        ],
        tmp_path,
    )
    msgs = list(iter_messages(corpus))
    assert len(msgs) == 1
    assert msgs[0].msg_id == 100


@pytest.mark.unit
def test_iter_messages_skips_empty_text(tmp_path: Path) -> None:
    corpus = _make_corpus(
        [
            _msg(1, 100, 1000.0, ""),
            _msg(1, 101, 1001.0, "   "),
            _msg(1, 102, 1002.0, "real text"),
        ],
        tmp_path,
    )
    msgs = list(iter_messages(corpus))
    assert [m.msg_id for m in msgs] == [102]


@pytest.mark.unit
def test_iter_messages_malformed_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"type": "message"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="parse error"):
        list(iter_messages(bad))


@pytest.mark.unit
def test_group_by_sender_filters_min_messages(tmp_path: Path) -> None:
    rows = [_msg(1, i, float(i), "hi") for i in range(5)]
    rows += [_msg(2, 100 + i, float(100 + i), "hi") for i in range(2)]
    corpus = _make_corpus(rows, tmp_path)
    grouped = group_by_sender(iter_messages(corpus), min_messages=3)
    assert 1 in grouped
    assert 2 not in grouped  # only 2 messages, under the 3-message floor


@pytest.mark.unit
def test_group_by_sender_excludes_channel_broadcasts(tmp_path: Path) -> None:
    rows = [_msg(-100, i, float(i)) for i in range(10)]
    rows += [_msg(50, 200 + i, float(200 + i)) for i in range(10)]
    corpus = _make_corpus(rows, tmp_path)
    grouped = group_by_sender(iter_messages(corpus), min_messages=3)
    assert 50 in grouped
    assert -100 not in grouped


@pytest.mark.unit
def test_group_by_sender_keeps_channels_when_flag_off(tmp_path: Path) -> None:
    rows = [_msg(-100, i, float(i)) for i in range(5)]
    corpus = _make_corpus(rows, tmp_path)
    grouped = group_by_sender(
        iter_messages(corpus), min_messages=3, exclude_channel_broadcasts=False
    )
    assert -100 in grouped


@pytest.mark.unit
def test_group_by_sender_sorts_chronologically(tmp_path: Path) -> None:
    rows = [
        _msg(1, 3, 30.0),
        _msg(1, 1, 10.0),
        _msg(1, 2, 20.0),
    ]
    corpus = _make_corpus(rows, tmp_path)
    grouped = group_by_sender(iter_messages(corpus), min_messages=2)
    assert [m.ts for m in grouped[1]] == [10.0, 20.0, 30.0]


@pytest.mark.unit
def test_split_halves_chronological_even() -> None:
    msgs = [RutifyMessage(1, i, 1, float(i), "x", None, None, ()) for i in range(10)]
    a, b = split_halves(msgs)
    assert len(a) == 5
    assert len(b) == 5
    assert a[-1].ts < b[0].ts


@pytest.mark.unit
def test_split_halves_chronological_odd() -> None:
    msgs = [RutifyMessage(1, i, 1, float(i), "x", None, None, ()) for i in range(9)]
    a, b = split_halves(msgs)
    # n//2 = 4 → first half 4, second half 5
    assert len(a) == 4
    assert len(b) == 5


@pytest.mark.unit
def test_split_halves_interleaved() -> None:
    msgs = [RutifyMessage(1, i, 1, float(i), "x", None, None, ()) for i in range(6)]
    a, b = split_halves(msgs, mode="interleaved")
    assert [m.msg_id for m in a] == [0, 2, 4]
    assert [m.msg_id for m in b] == [1, 3, 5]


@pytest.mark.unit
def test_split_halves_short_returns_empty() -> None:
    msgs = [RutifyMessage(1, 0, 1, 0.0, "x", None, None, ())]
    a, b = split_halves(msgs)
    assert a == []
    assert b == []


@pytest.mark.unit
def test_split_halves_unknown_mode_raises() -> None:
    msgs = [RutifyMessage(1, i, 1, float(i), "x", None, None, ()) for i in range(4)]
    with pytest.raises(ValueError, match="unknown split mode"):
        split_halves(msgs, mode="cosmic-rays")


@pytest.mark.unit
def test_token_count_whitespace_split() -> None:
    assert token_count("hola que tal") == 3
    assert token_count("") == 0
    assert token_count("   ") == 0


@pytest.mark.unit
def test_token_budget_report_empty() -> None:
    r = token_budget_report({})
    assert r.actor_count == 0
    assert r.p50 == 0


@pytest.mark.unit
def test_token_budget_report_counts_eligibility() -> None:
    # actor 1: 30 short msgs → fewer than 200 tokens, fewer than 500
    msgs_short = [RutifyMessage(1, i, 1, float(i), "a b", None, None, ()) for i in range(30)]
    # actor 2: 30 long msgs → 30 msgs * 200 tokens each = 6000 tokens
    big = " ".join(f"w{i}" for i in range(200))
    msgs_long = [RutifyMessage(1, 1000 + i, 2, float(i), big, None, None, ()) for i in range(30)]
    grouped = {1: msgs_short, 2: msgs_long}
    r = token_budget_report(grouped)
    assert r.actor_count == 2
    assert r.actors_above_200_per_half == 1  # actor 2 only
    assert r.actors_above_500_per_half == 1  # actor 2 only


@pytest.mark.unit
def test_evidence_ref_shape() -> None:
    m = RutifyMessage(42, 7, 99, 0.0, "x", None, None, ())
    assert m.evidence_ref == "rutify:42:7"
