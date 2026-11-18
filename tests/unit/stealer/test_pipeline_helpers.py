# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pipeline filesystem helpers: the nonempty-tree success signal used to detect
whether a password unlocked an archive (0-byte stubs vs real content)."""

from __future__ import annotations

from pathlib import Path

import pytest

from eyenet.stealer.pipeline import _any_nonempty_file

pytestmark = pytest.mark.unit


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
