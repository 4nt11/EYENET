"""document_corpus loaders — the loud-fail validation contract.

A calibration corpus is operator-curated; a malformed row is corruption, not
noise, and must raise rather than silently drop (a dropped sensitive doc would
hide an under-classification). These tests pin every validation branch.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from eyenet.calibration.document_corpus import (
    load_document_corpus,
    load_findings,
    sha256_file,
)
from eyenet.contracts.enums import SensitivityTier

pytestmark = pytest.mark.unit


def _w(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


# ---- corpus loader ---------------------------------------------------------


def test_loads_valid_corpus(tmp_path: Path) -> None:
    p = _w(
        tmp_path,
        "c.jsonl",
        '{"doc_id":"a","expected_tier":"normal","text":"hi","lang":"en"}\n'
        '{"doc_id":"b","expected_tier":"classified","text":"x","embedded_meta":{"k":"v"}}\n',
    )
    samples = load_document_corpus(p)
    assert [s.doc_id for s in samples] == ["a", "b"]
    assert samples[1].expected_tier is SensitivityTier.CLASSIFIED
    assert samples[1].embedded_meta == {"k": "v"}


def test_blank_lines_skipped(tmp_path: Path) -> None:
    p = _w(tmp_path, "c.jsonl", '\n{"doc_id":"a","expected_tier":"normal","text":"hi"}\n\n')
    assert len(load_document_corpus(p)) == 1


def test_malformed_json_raises(tmp_path: Path) -> None:
    p = _w(tmp_path, "c.jsonl", "{not json}\n")
    with pytest.raises(ValueError, match="parse error at line 1"):
        load_document_corpus(p)


def test_missing_doc_id_raises(tmp_path: Path) -> None:
    p = _w(tmp_path, "c.jsonl", '{"expected_tier":"normal","text":"hi"}\n')
    with pytest.raises(ValueError, match="missing/empty 'doc_id'"):
        load_document_corpus(p)


def test_non_string_text_raises(tmp_path: Path) -> None:
    p = _w(tmp_path, "c.jsonl", '{"doc_id":"a","expected_tier":"normal","text":123}\n')
    with pytest.raises(ValueError, match="'text' must be a string"):
        load_document_corpus(p)


def test_unknown_tier_raises(tmp_path: Path) -> None:
    p = _w(tmp_path, "c.jsonl", '{"doc_id":"a","expected_tier":"ultra","text":"hi"}\n')
    with pytest.raises(ValueError, match="expected_tier"):
        load_document_corpus(p)


def test_duplicate_doc_id_raises(tmp_path: Path) -> None:
    p = _w(
        tmp_path,
        "c.jsonl",
        '{"doc_id":"a","expected_tier":"normal","text":"1"}\n'
        '{"doc_id":"a","expected_tier":"normal","text":"2"}\n',
    )
    with pytest.raises(ValueError, match="duplicate doc_id"):
        load_document_corpus(p)


def test_non_string_lang_and_notes_default(tmp_path: Path) -> None:
    p = _w(
        tmp_path,
        "c.jsonl",
        '{"doc_id":"a","expected_tier":"normal","text":"hi","lang":5,"notes":9}\n',
    )
    s = load_document_corpus(p)[0]
    assert s.lang is None and s.notes == ""


# ---- findings sidecar loader -----------------------------------------------


def test_loads_findings(tmp_path: Path) -> None:
    p = _w(
        tmp_path,
        "f.jsonl",
        '{"doc_id":"a","findings":[]}\n'
        '{"doc_id":"b","findings":[{"entity_type":"PERSON","start":0,"end":4,'
        '"score":0.9,"language":"en","text":"Juan"}]}\n',
    )
    out = load_findings(p)
    assert out["a"] == ()
    assert out["b"][0].entity_type == "PERSON"


def test_findings_bad_json_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="parse error"):
        load_findings(_w(tmp_path, "f.jsonl", "nope\n"))


def test_findings_missing_doc_id_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="missing/empty 'doc_id'"):
        load_findings(_w(tmp_path, "f.jsonl", '{"findings":[]}\n'))


def test_findings_non_list_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="'findings' must be a list"):
        load_findings(_w(tmp_path, "f.jsonl", '{"doc_id":"a","findings":5}\n'))


def test_findings_non_object_entry_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="must be an object"):
        load_findings(_w(tmp_path, "f.jsonl", '{"doc_id":"a","findings":["x"]}\n'))


def test_findings_malformed_entry_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="malformed finding"):
        load_findings(_w(tmp_path, "f.jsonl", '{"doc_id":"a","findings":[{"entity_type":"P"}]}\n'))


def test_findings_blank_lines_skipped(tmp_path: Path) -> None:
    assert load_findings(_w(tmp_path, "f.jsonl", '\n{"doc_id":"a","findings":[]}\n\n')) == {"a": ()}


# ---- sha256 pin ------------------------------------------------------------


def test_sha256_file_is_stable(tmp_path: Path) -> None:
    p = _w(tmp_path, "c.jsonl", "content\n")
    assert sha256_file(p) == sha256_file(p)
    assert len(sha256_file(p)) == 64
