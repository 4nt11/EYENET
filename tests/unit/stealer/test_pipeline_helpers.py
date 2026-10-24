# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pipeline filesystem helpers: password-file discovery + the nonempty success signal.

The subprocess parts (unar extract, ulpextract) are integration; these pure helpers
decide password success and which files feed the extractor, so they're unit-tested."""

from __future__ import annotations

from pathlib import Path

import pytest

from eyenet.stealer.pipeline import _any_nonempty_file, _find_password_files

pytestmark = pytest.mark.unit


def test_find_password_files_recursive_case_insensitive(tmp_path: Path) -> None:
    (tmp_path / "chan/machine_A/sub").mkdir(parents=True)
    (tmp_path / "chan/machine_A/passwords.txt").write_text("x")
    (tmp_path / "chan/machine_A/sub/All Passwords.txt").write_text("x")
    (tmp_path / "chan/machine_A/Passwords.txt").write_text("x")
    (tmp_path / "chan/machine_A/cookies.txt").write_text("x")  # not a password file

    found = {p.name for p in _find_password_files(tmp_path)}
    assert found == {"passwords.txt", "All Passwords.txt", "Passwords.txt"}


def test_any_nonempty_file_distinguishes_stubs_from_content(tmp_path: Path) -> None:
    # Wrong-password extraction leaves 0-byte stubs — must read as "no content".
    stubs = tmp_path / "wrong"
    (stubs / "d").mkdir(parents=True)
    (stubs / "d/a.txt").write_text("")  # 0 bytes
    (stubs / "d/b.txt").write_text("")
    assert _any_nonempty_file(stubs) is False

    # Right-password extraction has real bytes somewhere.
    good = tmp_path / "right"
    (good / "d").mkdir(parents=True)
    (good / "d/a.txt").write_text("")
    (good / "d/b.txt").write_text("Login: x")
    assert _any_nonempty_file(good) is True


def test_any_nonempty_file_empty_tree(tmp_path: Path) -> None:
    assert _any_nonempty_file(tmp_path) is False
