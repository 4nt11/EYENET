"""CRUD + path-safety tests for the on-disk stealer rule catalog.

The HTTP layer is a thin FastAPI wrapper over the rw module; we test
the rw module directly to keep the suite independent of the API deps.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from eyenet.stealer.rules.catalog import rw

pytestmark = pytest.mark.unit


@pytest.fixture
def tmp_rules_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("EYENET_STEALER_RULES_DIR", str(tmp_path))
    return tmp_path


def _rule(slug: str = "test_rule", *, family: str = "lumma") -> dict[str, Any]:
    return {
        "id": slug,
        "version": 1,
        "layer": "content",
        "family": family,
        "priority": 100,
        "match": {"type": "regex", "pattern": "^X$"},
    }


def test_write_then_read(tmp_rules_dir: Path) -> None:
    rw.write_rule(_rule("my_rule"), allow_overwrite=False)
    assert (tmp_rules_dir / "my_rule.yaml").is_file()
    back = rw.read_rule("my_rule")
    assert back["id"] == "my_rule"
    assert back["match"]["type"] == "regex"


def test_create_rejects_overwrite(tmp_rules_dir: Path) -> None:
    rw.write_rule(_rule("dup"), allow_overwrite=False)
    with pytest.raises(FileExistsError):
        rw.write_rule(_rule("dup"), allow_overwrite=False)


def test_replace_allows_overwrite(tmp_rules_dir: Path) -> None:
    rw.write_rule(_rule("replaceable"), allow_overwrite=False)
    updated = _rule("replaceable")
    updated["priority"] = 999
    rw.write_rule(updated, allow_overwrite=True)
    assert rw.read_rule("replaceable")["priority"] == 999


def test_delete_removes_file(tmp_rules_dir: Path) -> None:
    rw.write_rule(_rule("to_delete"), allow_overwrite=False)
    rw.delete_rule("to_delete")
    assert not (tmp_rules_dir / "to_delete.yaml").exists()
    with pytest.raises(FileNotFoundError):
        rw.read_rule("to_delete")


@pytest.mark.parametrize(
    "bad_slug",
    [
        "../escape",  # path traversal
        "/absolute",  # rooted
        "has spaces",  # whitespace
        "UPPER",  # uppercase
        "bad.dot",  # dot in slug
        "1_starts_with_num",  # leading digit
        "x",  # too short
        "a" * 65,  # too long
    ],
)
def test_slug_rejects_unsafe_input(tmp_rules_dir: Path, bad_slug: str) -> None:
    with pytest.raises(ValueError, match="slug"):
        rw._enforce_slug(bad_slug)
    with pytest.raises(ValueError, match="slug"):
        rw.read_rule(bad_slug)


def test_atomic_write_leaves_no_tempfile(tmp_rules_dir: Path) -> None:
    rw.write_rule(_rule("atomic"), allow_overwrite=False)
    leftover = [p.name for p in tmp_rules_dir.iterdir() if p.name.startswith(".")]
    assert leftover == [], f"tempfile not cleaned up: {leftover}"


def test_shape_validation_requires_core_fields(tmp_rules_dir: Path) -> None:
    for field in ("id", "version", "layer", "family", "priority", "match"):
        bad = _rule("shape_test")
        bad.pop(field)
        with pytest.raises(ValueError, match=field):
            rw.write_rule(bad, allow_overwrite=False)


def test_shape_validation_rejects_unknown_match_type(tmp_rules_dir: Path) -> None:
    bad = _rule("bad_type")
    bad["match"] = {"type": "not_a_real_matcher"}
    with pytest.raises(ValueError, match=r"match\.type"):
        rw.write_rule(bad, allow_overwrite=False)


def test_unknown_family_warns_but_does_not_block(
    tmp_rules_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    rule = _rule("exp_family", family="brand_new_family_not_in_catalog")
    import logging

    with caplog.at_level(logging.WARNING, logger="eyenet.stealer.rules.catalog.rw"):
        rw.write_rule(rule, allow_overwrite=False)
    assert any("unknown family" in r.message for r in caplog.records)
    assert (tmp_rules_dir / "exp_family.yaml").is_file()
