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


def _fam(
    slug: str = "test_fam", *, status: str = "new", kind: str = "stealer"
) -> dict[str, object]:
    return {"slug": slug, "name": slug.capitalize(), "status": status, "kind": kind}


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
    with pytest.raises(ValueError, match="invalid slug"):
        rw._enforce_slug(bad_slug)
    with pytest.raises(ValueError, match="invalid slug"):
        rw.read_family(bad_slug)


def test_shape_validation_requires_core_fields(tmp_families_dir: Path) -> None:
    for field in ("slug", "name", "status", "kind"):
        bad = _fam("shape_test")
        bad.pop(field)
        with pytest.raises(ValueError, match=field):
            rw.write_family(bad, allow_overwrite=False)


def test_shape_validation_rejects_unknown_status(tmp_families_dir: Path) -> None:
    bad = _fam("bad_status", status="undead")
    with pytest.raises(ValueError, match="status"):
        rw.write_family(bad, allow_overwrite=False)


def test_shape_validation_rejects_unknown_kind(tmp_families_dir: Path) -> None:
    bad = _fam("bad_kind", kind="malware")
    with pytest.raises(ValueError, match="kind"):
        rw.write_family(bad, allow_overwrite=False)


def test_classifier_signals_optional_and_shape_checked(tmp_families_dir: Path) -> None:
    good = _fam("signalled", kind="stealer")
    good["signature_paths"] = ["Browser/Cookies/", "Autofills/"]
    good["signature_rule_ids"] = ["stealer_info_yaml"]
    good["build_tag_regex"] = r"^(mix|stealc_.*)$"
    good["confidence_floor"] = 0.35
    good["signal_weights"] = {"build_tag": 5.0, "sig_rule": 2.0}
    rw.write_family(good, allow_overwrite=False)
    back = rw.read_family("signalled")
    assert back["signature_paths"] == ["Browser/Cookies/", "Autofills/"]
    assert back["build_tag_regex"] == r"^(mix|stealc_.*)$"

    bad_weights = _fam("bad_weight_key", kind="stealer")
    bad_weights["signal_weights"] = {"sig_file": 1.0, "unknown_signal_key": 0.1}
    with pytest.raises(ValueError, match="unknown_signal_key"):
        rw.write_family(bad_weights, allow_overwrite=False)

    bad_regex = _fam("bad_regex", kind="stealer")
    bad_regex["build_tag_regex"] = "([unclosed"
    with pytest.raises(ValueError, match="build_tag_regex"):
        rw.write_family(bad_regex, allow_overwrite=False)

    bad_floor = _fam("bad_floor", kind="stealer")
    bad_floor["confidence_floor"] = 1.5
    with pytest.raises(ValueError, match="confidence_floor"):
        rw.write_family(bad_floor, allow_overwrite=False)


def test_atomic_write_leaves_no_tempfile(tmp_families_dir: Path) -> None:
    rw.write_family(_fam("atomic"), allow_overwrite=False)
    leftover = [p.name for p in tmp_families_dir.iterdir() if p.name.startswith(".")]
    assert leftover == [], f"tempfile not cleaned up: {leftover}"
