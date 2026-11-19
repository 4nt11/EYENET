# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for the file_scan heuristic classifier (v1.2.6 observability).

Covers the classification branches that matter for "what did we see, what are
we parsing, what are we missing" operator queries against stealer.file_audit.
The classifier is a side-channel; precision beats recall here (false-positive
'likely_meta' is worse than false-negative 'text_unknown' because unknown
files are what the audit workflow surfaces for rule-authoring).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from eyenet.stealer.file_scan import scan_file, walk_audit

pytestmark = pytest.mark.unit


def _write(tmp: Path, name: str, data: bytes | str) -> Path:
    p = tmp / name
    p.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
    return p


def test_empty_file(tmp_path: Path) -> None:
    p = _write(tmp_path, "empty.txt", b"")
    a = scan_file(p, "empty.txt")
    assert a.heuristic_kind == "empty"
    assert a.size_bytes == 0
    assert a.sample_head == ""


def test_known_metadata_filename_wins_even_with_banner(tmp_path: Path) -> None:
    # Classification should KEY ON FILENAME for the known metadata list, so
    # a StealC information.txt with its banner header still scores as
    # likely_meta (and NOT likely_creds, which the banner lines could hit).
    # The banner lines also tick approx_banner_hits so the operator sees
    # "this file is meta AND it carries banner noise" at a glance.
    content = (
        "TG t.me/+SomeInvite\nTELEGRAM - t.me/+other\n\nWindows: Windows 10\nUser Name: alice\n"
    )
    p = _write(tmp_path, "information.txt", content)
    a = scan_file(p, "information.txt")
    assert a.heuristic_kind == "likely_meta"
    assert a.approx_banner_hits >= 2


def test_json_family_pc_info(tmp_path: Path) -> None:
    p = _write(tmp_path, "pc_info.json", '{"PcName":"X","Ip":"1.2.3.4"}')
    a = scan_file(p, "pc_info.json")
    # Known filename wins the meta label before the JSON check.
    assert a.heuristic_kind == "likely_meta"


def test_bare_json_without_known_filename(tmp_path: Path) -> None:
    p = _write(tmp_path, "something.json", '{"foo": 1}')
    a = scan_file(p, "something.json")
    assert a.heuristic_kind == "likely_json"


def test_png_magic_bytes(tmp_path: Path) -> None:
    p = _write(tmp_path, "screen.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    a = scan_file(p, "screen.png")
    assert a.heuristic_kind == "likely_screenshot"


def test_rar_archive_magic_bytes(tmp_path: Path) -> None:
    p = _write(tmp_path, "nested.rar", b"Rar!\x1a\x07\x00" + b"\x00" * 100)
    a = scan_file(p, "nested.rar")
    assert a.heuristic_kind == "likely_archive"


def test_credential_shape_text(tmp_path: Path) -> None:
    # URL:USER:PASS layout should land as likely_creds for unknown filenames.
    content = "https://example.com:alice:hunter2\nhttps://another.com:bob:p455\n"
    p = _write(tmp_path, "mystery_dump.txt", content)
    a = scan_file(p, "mystery_dump.txt")
    assert a.heuristic_kind == "likely_creds"


def test_banner_hits_counted(tmp_path: Path) -> None:
    content = "TG t.me/+abc\nTELEGRAM - t.me/+def\nhttps://real.com:user:realpass\n"
    p = _write(tmp_path, "banner_salad.txt", content)
    a = scan_file(p, "banner_salad.txt")
    # Three hits, not two: "TG " + "TELEGRAM " are two anchored-start matches;
    # the " t.me/" sub-match on the second line fires separately. The counter
    # is a "approximate banner density" signal, not an exact per-line count.
    assert a.approx_banner_hits >= 2


def test_null_pw_hits_counted(tmp_path: Path) -> None:
    content = "host1.com:alice:Null\nhost2.com:bob:none\nhost3.com:charlie:realpass\n"
    p = _write(tmp_path, "mixed.txt", content)
    a = scan_file(p, "mixed.txt")
    assert a.approx_null_pw_hits == 2


def test_binary_blob_classification(tmp_path: Path) -> None:
    # 80% non-printable bytes -> binary (below the 70% printable threshold).
    p = _write(tmp_path, "blob.bin", b"\x01\x02\x03\xff\xfe\xfd" * 300)
    a = scan_file(p, "blob.bin")
    assert a.heuristic_kind == "binary"


def test_walk_audit_yields_every_regular_file(tmp_path: Path) -> None:
    (tmp_path / "subdir").mkdir()
    _write(tmp_path, "a.txt", "hello world line one")
    _write(tmp_path, "subdir/b.txt", "another")
    audits = list(walk_audit(tmp_path))
    rel_paths = {a.rel_path for a in audits}
    assert rel_paths == {"a.txt", "subdir/b.txt"}


def test_file_sha256_stable(tmp_path: Path) -> None:
    # Known input -> known sha. Dedup in ReplacingMergeTree relies on this.
    p = _write(tmp_path, "x.txt", b"hello")
    a = scan_file(p, "x.txt")
    assert (
        a.file_sha256 == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    )  # pragma: allowlist secret
