"""Profile builders: host-resource discovery -> least-privilege recipes."""

from __future__ import annotations

from pathlib import Path

import pytest

from eyenet.classifier.sandbox import _profiles as pf
from eyenet.classifier.sandbox._policy import (
    INPUT_DEST,
    SINGLE_THREAD_ENV,
    TESSDATA_DEST,
    VENV_SITE_DEST,
)

pytestmark = pytest.mark.unit


# ---- resolve_extract_venv / venv_site_packages ----------------------------


def test_resolve_extract_venv_honours_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("EYENET_EXTRACT_VENV", str(tmp_path))
    assert pf.resolve_extract_venv() == tmp_path


def test_resolve_extract_venv_none_when_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EYENET_EXTRACT_VENV", "/no/such/venv/anywhere")
    assert pf.resolve_extract_venv() is None


def test_venv_site_packages_finds_versioned_dir(tmp_path: Path) -> None:
    site = tmp_path / "lib" / "python3.12" / "site-packages"
    site.mkdir(parents=True)
    assert pf.venv_site_packages(tmp_path) == site


def test_venv_site_packages_none_when_missing(tmp_path: Path) -> None:
    assert pf.venv_site_packages(tmp_path) is None


# ---- discover_tesseract ---------------------------------------------------


def test_discover_tesseract_uses_env_prefix(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(pf.shutil, "which", lambda _n: "/usr/bin/tesseract")
    monkeypatch.setenv("TESSDATA_PREFIX", str(tmp_path))
    binary, tessdata = pf.discover_tesseract()
    assert binary == "/usr/bin/tesseract" and tessdata == str(tmp_path)


def test_discover_tesseract_none_when_binary_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pf.shutil, "which", lambda _n: None)
    assert pf.discover_tesseract() == (None, None)


# ---- venv_profile ---------------------------------------------------------


def test_venv_profile_binds_site_and_sets_pythonpath(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    site = tmp_path / "lib" / "python3.12" / "site-packages"
    site.mkdir(parents=True)
    monkeypatch.setattr(pf, "resolve_extract_venv", lambda: tmp_path)
    profile = pf.venv_profile()
    assert profile is not None
    assert (str(site), VENV_SITE_DEST) in profile.extra_ro_binds
    assert ("PYTHONPATH", VENV_SITE_DEST) in profile.env
    # single-thread env is always present so C-ext libs never spawn threads
    for pair in SINGLE_THREAD_ENV:
        assert pair in profile.env
    assert profile.entrypoint is None  # Python worker, not a raw entrypoint


def test_venv_profile_none_when_venv_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pf, "resolve_extract_venv", lambda: None)
    assert pf.venv_profile() is None


# ---- tesseract_profile ----------------------------------------------------


def test_tesseract_profile_builds_entrypoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pf, "discover_tesseract", lambda: ("/usr/bin/tesseract", "/data/tessdata"))
    profile = pf.tesseract_profile(langs="spa")
    assert profile is not None
    assert profile.entrypoint == ("/usr/bin/tesseract", INPUT_DEST, "stdout", "-l", "spa")
    assert ("/data/tessdata", TESSDATA_DEST) in profile.extra_ro_binds
    assert ("TESSDATA_PREFIX", TESSDATA_DEST) in profile.env
    for pair in SINGLE_THREAD_ENV:
        assert pair in profile.env


def test_tesseract_profile_without_tessdata_still_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pf, "discover_tesseract", lambda: ("/usr/bin/tesseract", None))
    profile = pf.tesseract_profile()
    assert profile is not None
    assert profile.extra_ro_binds == ()
    assert profile.env == SINGLE_THREAD_ENV  # only the single-thread limits


def test_tesseract_profile_none_when_binary_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pf, "discover_tesseract", lambda: (None, None))
    assert pf.tesseract_profile() is None


def test_stdlib_profile_is_the_base_recipe() -> None:
    profile = pf.stdlib_profile()
    assert profile.entrypoint is None
    assert profile.extra_ro_binds == ()
    assert profile.env == ()
