# SPDX-License-Identifier: AGPL-3.0-or-later
"""Archive-attack hardening for the tdata import extractor.

These pin the security surface of ``eyenet.identity_pool._tdata`` - zip-slip,
absolute paths, zip-bombs (count / per-file / total), and tar symlink escapes -
plus the happy path and the tdata-root finder. The opentele conversion itself
needs a real tdata and is not exercised here; the attack surface is extraction."""

from __future__ import annotations

import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from eyenet.identity_pool import _tdata
from eyenet.identity_pool._provision import SessionValidationError

pytestmark = pytest.mark.unit


def _zip(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_happy_path_extracts_confined(tmp_path: Path) -> None:
    archive = _zip({"tdata/key_datas": b"\x00key", "tdata/D877/map0": b"\x00map"})
    dest = tmp_path / "out"
    dest.mkdir()
    _tdata.extract_archive_safely(archive, dest)
    assert (dest / "tdata" / "key_datas").read_bytes() == b"\x00key"
    assert (dest / "tdata" / "D877" / "map0").is_file()


def test_find_tdata_root_shallowest(tmp_path: Path) -> None:
    archive = _zip({"wrap/tdata/key_datas": b"k", "wrap/tdata/x/y/key_datas": b"k"})
    dest = tmp_path / "out"
    dest.mkdir()
    _tdata.extract_archive_safely(archive, dest)
    root = _tdata._find_tdata_root(dest)
    assert root == (dest / "wrap" / "tdata").resolve()


def test_find_tdata_root_missing(tmp_path: Path) -> None:
    archive = _zip({"notdata/readme.txt": b"nope"})
    dest = tmp_path / "out"
    dest.mkdir()
    _tdata.extract_archive_safely(archive, dest)
    with pytest.raises(SessionValidationError, match="no_tdata_found"):
        _tdata._find_tdata_root(dest)


def test_zip_slip_rejected(tmp_path: Path) -> None:
    archive = _zip({"../escape.txt": b"pwned"})
    dest = tmp_path / "out"
    dest.mkdir()
    with pytest.raises(SessionValidationError, match="archive_path_escape"):
        _tdata.extract_archive_safely(archive, dest)
    assert not (tmp_path / "escape.txt").exists()


def test_absolute_path_rejected(tmp_path: Path) -> None:
    archive = _zip({"/etc/evil": b"pwned"})
    dest = tmp_path / "out"
    dest.mkdir()
    with pytest.raises(SessionValidationError, match="archive_absolute_path"):
        _tdata.extract_archive_safely(archive, dest)


def test_too_many_entries_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_tdata, "_MAX_ENTRIES", 3)
    archive = _zip({f"tdata/f{i}": b"x" for i in range(5)})
    dest = tmp_path / "out"
    dest.mkdir()
    with pytest.raises(SessionValidationError, match="archive_too_many_entries"):
        _tdata.extract_archive_safely(archive, dest)


def test_per_file_cap_during_stream(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # The streaming cap must trip even though the header is honest; shrink the cap
    # rather than build a 50MB fixture.
    monkeypatch.setattr(_tdata, "_MAX_FILE_BYTES", 16)
    monkeypatch.setattr(_tdata, "_MAX_RATIO", 10**9)  # don't let the ratio guard pre-empt it
    archive = _zip({"tdata/big": b"A" * 1024})
    dest = tmp_path / "out"
    dest.mkdir()
    with pytest.raises(SessionValidationError, match="archive_file_too_large"):
        _tdata.extract_archive_safely(archive, dest)


def test_total_cap_across_members(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_tdata, "_MAX_TOTAL_BYTES", 20)
    monkeypatch.setattr(_tdata, "_MAX_RATIO", 10**9)
    archive = _zip({"tdata/a": b"A" * 15, "tdata/b": b"B" * 15})
    dest = tmp_path / "out"
    dest.mkdir()
    with pytest.raises(SessionValidationError, match="archive_total_too_large"):
        _tdata.extract_archive_safely(archive, dest)


def test_tar_symlink_rejected(tmp_path: Path) -> None:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        info = tarfile.TarInfo("tdata/link")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        tf.addfile(info)
    dest = tmp_path / "out"
    dest.mkdir()
    with pytest.raises(SessionValidationError, match="archive_unsafe_member_type"):
        _tdata.extract_archive_safely(buf.getvalue(), dest)


def test_unsupported_format_rejected(tmp_path: Path) -> None:
    dest = tmp_path / "out"
    dest.mkdir()
    with pytest.raises(SessionValidationError, match="unsupported_archive_format"):
        _tdata.extract_archive_safely(b"not an archive, just bytes", dest)


def test_oversize_archive_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_tdata, "_MAX_ARCHIVE_BYTES", 8)
    dest = tmp_path / "out"
    dest.mkdir()
    with pytest.raises(SessionValidationError, match="archive_too_large"):
        _tdata.extract_archive_safely(b"0123456789", dest)
