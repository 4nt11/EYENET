"""load_llm_config(): strict TOML load, env override, fail-closed validation."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from eyenet.classifier.llm import LLM_CONFIG_ENV, load_llm_config

pytestmark = pytest.mark.unit

_MINIMAL = 'config_version = "t"\nmodel = "test-model"\n'


def test_bundled_default_loads() -> None:
    cfg = load_llm_config()
    assert cfg.model == "llama3.1"
    assert cfg.allow_remote is False
    assert cfg.endpoint.startswith("http://127.0.0.1")


def test_explicit_path_wins(tmp_path: Path) -> None:
    p = tmp_path / "llm.toml"
    p.write_text(_MINIMAL, encoding="utf-8")
    cfg = load_llm_config(p)
    assert cfg.model == "test-model"
    assert cfg.endpoint == "http://127.0.0.1:11434"  # defaulted


def test_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    p = tmp_path / "override.toml"
    p.write_text(
        'config_version = "t"\nmodel = "env-model"\nallow_remote = true\n', encoding="utf-8"
    )
    monkeypatch.setenv(LLM_CONFIG_ENV, str(p))
    cfg = load_llm_config()
    assert cfg.model == "env-model"
    assert cfg.allow_remote is True


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_llm_config(tmp_path / "nope.toml")


def test_unknown_key_is_rejected(tmp_path: Path) -> None:
    p = tmp_path / "bad.toml"
    p.write_text(_MINIMAL + 'bogus = "x"\n', encoding="utf-8")
    with pytest.raises(ValidationError):
        load_llm_config(p)


def test_out_of_range_value_is_rejected(tmp_path: Path) -> None:
    p = tmp_path / "bad.toml"
    p.write_text(_MINIMAL + "max_attempts = 0\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        load_llm_config(p)
