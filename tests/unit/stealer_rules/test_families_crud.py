"""CRUD + path-safety tests for the on-disk family catalog.

Mirrors ``test_rules_crud.py`` so the shape stays familiar; family rw
and rule rw are intentionally symmetric.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from eyenet.stealer.families import rw

pytestmark = pytest.mark.unit


@pytest.fixture
def tmp_families_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("EYENET_STEALER_FAMILIES_DIR", str(tmp_path))
    return tmp_path


def _fam(slug: str = "test_fam", *, status: str = "new") -> dict:
    return {"slug": slug, "name": slug.capitalize(), "status": status}


def test_write_then_read(tmp_families_dir: Path) -> None:
    rw.write_family(_fam("lumma_like"), allow_overwrite=False)
    assert (tmp_families_dir / "lumma_like.yaml").is_file()
    back = rw.read_family("lumma_like")
    assert back["slug"] == "lumma_like"
    assert back["status"] == "new"


def test_create_rejects_overwrite(tmp_families_dir: Path) -> None:
    rw.write_family(_fam("dup"), allow_overwrite=False)
    with pytest.raises(FileExistsError):
        rw.write_family(_fam("dup"), allow_overwrite=False)


def test_replace_allows_overwrite(tmp_families_dir: Path) -> None:
    rw.write_family(_fam("replaceable"), allow_overwrite=False)
    updated = _fam("replaceable", status="active")
    rw.write_family(updated, allow_overwrite=True)
    assert rw.read_family("replaceable")["status"] == "active"


def test_delete_removes_file(tmp_families_dir: Path) -> None:
    rw.write_family(_fam("to_delete"), allow_overwrite=False)
    rw.delete_family("to_delete")
    assert not (tmp_families_dir / "to_delete.yaml").exists()


@pytest.mark.parametrize(
    "bad_slug",
    ["../escape", "/absolute", "has spaces", "UPPER", "bad.dot", "1leading", "x", "a" * 65],
)
def test_slug_rejects_unsafe_input(tmp_families_dir: Path, bad_slug: str) -> None:
    with pytest.raises(ValueError):
        rw._enforce_slug(bad_slug)
    with pytest.raises(ValueError):
        rw.read_family(bad_slug)


def test_shape_validation_requires_core_fields(tmp_families_dir: Path) -> None:
    for field in ("slug", "name", "status"):
        bad = _fam("shape_test")
        bad.pop(field)
        with pytest.raises(ValueError, match=field):
            rw.write_family(bad, allow_overwrite=False)


def test_shape_validation_rejects_unknown_status(tmp_families_dir: Path) -> None:
    bad = _fam("bad_status", status="undead")
    with pytest.raises(ValueError, match="status"):
        rw.write_family(bad, allow_overwrite=False)


def test_atomic_write_leaves_no_tempfile(tmp_families_dir: Path) -> None:
    rw.write_family(_fam("atomic"), allow_overwrite=False)
    leftover = [p.name for p in tmp_families_dir.iterdir() if p.name.startswith(".")]
    assert leftover == [], f"tempfile not cleaned up: {leftover}"
