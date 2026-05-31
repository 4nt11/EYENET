"""sanitize_model_text(): neutralize hostile model output at the boundary.

This is the CVE-prevention core — the model's free text is treated as a
stored-XSS / log-injection / terminal-escape payload and made inert before it is
ever stored or logged.
"""

from __future__ import annotations

import pytest

from eyenet.classifier.llm._sanitize import sanitize_model_text

pytestmark = pytest.mark.unit


def test_script_tag_is_escaped_not_executable() -> None:
    out = sanitize_model_text("<script>alert(1)</script>", max_len=200)
    assert "<script>" not in out
    assert "<" not in out and ">" not in out
    assert "&lt;script&gt;" in out


def test_nested_broken_tag_cannot_reform() -> None:
    # Tag-stripping would leave "<script>"; escaping makes a tag impossible.
    out = sanitize_model_text("<scr<script>ipt>", max_len=200)
    assert "<" not in out
    assert "&lt;" in out


def test_ansi_escape_sequences_are_stripped_whole() -> None:
    out = sanitize_model_text("hello\x1b[31mRED\x1b[0m world", max_len=200)
    assert "\x1b" not in out
    assert "[31m" not in out  # the sequence vanished, not just the ESC byte
    assert "hello" in out and "RED" in out and "world" in out


def test_c1_csi_introducer_is_removed() -> None:
    assert "\x9b" not in sanitize_model_text("a\x9b31mb", max_len=200)


def test_nul_and_control_bytes_become_space() -> None:
    out = sanitize_model_text("a\x00b\x07c\x1fd", max_len=200)
    assert "\x00" not in out
    assert all(ord(c) >= 0x20 for c in out)
    assert out == "a b c d"


def test_unicode_is_nfc_normalized() -> None:
    out = sanitize_model_text("é", max_len=200)  # e + combining acute
    assert "́" not in out
    assert out == "é"  # NFC: é


def test_length_is_capped() -> None:
    assert sanitize_model_text("abcdefghij", max_len=5) == "abcde"


def test_truncation_precedes_escape_so_entities_never_split() -> None:
    # "<" would become "&lt;"; truncating before escape avoids a split "&l".
    out = sanitize_model_text("<<<<<<<<<<", max_len=2)
    assert out == "&lt;&lt;"


def test_quotes_and_ampersand_escaped() -> None:
    out = sanitize_model_text("a & \"b\" 'c'", max_len=200)
    assert "&amp;" in out
    assert "&quot;" in out
    assert "&#x27;" in out


def test_whitespace_collapsed() -> None:
    assert sanitize_model_text("a\t\n  b\r\nc", max_len=200) == "a b c"


def test_benign_text_is_preserved() -> None:
    assert sanitize_model_text("Just a normal summary.", max_len=200) == "Just a normal summary."
