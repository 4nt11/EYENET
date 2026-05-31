"""PII-map loader: strict shape, range validation, parked entities, env override."""

from __future__ import annotations

from pathlib import Path

import pytest

from eyenet.classifier.presidio import PiiMap, load_pii_map
from eyenet.classifier.presidio._loader import PII_MAP_ENV
from eyenet.contracts.enums import SensitivityTier

pytestmark = pytest.mark.unit

_MINIMAL = (
    "map_version='v'\n"
    "[density]\nrestricted_at=3\nclassified_at=5\n"
    "[[entities]]\nname='US_SSN'\ntier_floor='classified'\n"
)


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "pii.toml"
    path.write_text(body, "utf-8")
    return path


# ---- bundled default -------------------------------------------------------


def test_bundled_default_loads() -> None:
    m = load_pii_map()
    assert isinstance(m, PiiMap)
    assert m.map_version == "v2"
    assert m.entities["US_SSN"].tier_floor is SensitivityTier.CLASSIFIED
    # v2 recalibration: contact-info PII (email/phone/location/IP) demoted to
    # NORMAL — slice-9 grid proved their presence over-classified benign docs.
    assert m.entities["EMAIL_ADDRESS"].tier_floor is SensitivityTier.NORMAL
    assert m.entities["PERSON"].tier_floor is SensitivityTier.NORMAL
    # v2 density counts STRONG identifiers only, so the cut-offs are small.
    assert m.restricted_at == 4
    assert m.classified_at == 8


def test_bundled_default_parks_noisy_ner_types() -> None:
    # DATE_TIME / URL fire on near-every document; they must ship parked so they
    # cannot inflate the density signal and collapse NORMAL into noise.
    m = load_pii_map()
    assert {"DATE_TIME", "URL"}.isdisjoint(m.entities)


def test_default_min_scores_in_unit_range() -> None:
    m = load_pii_map()
    assert all(0.0 <= rule.min_score <= 1.0 for rule in m.entities.values())


# ---- path / env resolution -------------------------------------------------


def test_explicit_path_overrides_default(tmp_path: Path) -> None:
    m = load_pii_map(_write(tmp_path, _MINIMAL))
    assert m.map_version == "v"
    assert set(m.entities) == {"US_SSN"}


def test_env_override_used_when_no_arg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _write(tmp_path, _MINIMAL.replace("map_version='v'", "map_version='env'"))
    monkeypatch.setenv(PII_MAP_ENV, str(path))
    assert load_pii_map().map_version == "env"


def test_explicit_arg_beats_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_file = _write(tmp_path, _MINIMAL.replace("map_version='v'", "map_version='env'"))
    arg_file = tmp_path / "arg.toml"
    arg_file.write_text(_MINIMAL.replace("map_version='v'", "map_version='arg'"), "utf-8")
    monkeypatch.setenv(PII_MAP_ENV, str(env_file))
    assert load_pii_map(arg_file).map_version == "arg"


def test_missing_file_raises_filenotfound(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_pii_map(tmp_path / "nope.toml")


# ---- fail-closed validation ------------------------------------------------


def test_unknown_key_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Extra inputs"):  # pydantic extra='forbid'
        load_pii_map(_write(tmp_path, _MINIMAL + "bogus=1\n"))


def test_bad_tier_rejected(tmp_path: Path) -> None:
    body = (
        "map_version='v'\n[density]\nrestricted_at=3\nclassified_at=5\n"
        "[[entities]]\nname='X'\ntier_floor='ultra'\n"
    )
    with pytest.raises(ValueError, match="Input should be"):
        load_pii_map(_write(tmp_path, body))


def test_min_score_out_of_range_rejected(tmp_path: Path) -> None:
    body = (
        "map_version='v'\n[density]\nrestricted_at=3\nclassified_at=5\n"
        "[[entities]]\nname='X'\ntier_floor='restricted'\nmin_score=1.5\n"
    )
    with pytest.raises(ValueError, match="less than or equal to 1"):
        load_pii_map(_write(tmp_path, body))


def test_inverted_density_thresholds_rejected(tmp_path: Path) -> None:
    body = (
        "map_version='v'\n[density]\nrestricted_at=10\nclassified_at=3\n"
        "[[entities]]\nname='X'\ntier_floor='restricted'\n"
    )
    with pytest.raises(ValueError, match="must be >= restricted_at"):
        load_pii_map(_write(tmp_path, body))


def test_duplicate_entity_rejected(tmp_path: Path) -> None:
    body = (
        "map_version='v'\n[density]\nrestricted_at=3\nclassified_at=5\n"
        "[[entities]]\nname='dup'\ntier_floor='normal'\n"
        "[[entities]]\nname='dup'\ntier_floor='restricted'\n"
    )
    with pytest.raises(ValueError, match="duplicate PII entity"):
        load_pii_map(_write(tmp_path, body))


# ---- enabled flag (parked entities) ----------------------------------------


def test_disabled_entity_excluded(tmp_path: Path) -> None:
    body = (
        "map_version='v'\n[density]\nrestricted_at=3\nclassified_at=5\n"
        "[[entities]]\nname='on'\ntier_floor='restricted'\n"
        "[[entities]]\nname='off'\ntier_floor='restricted'\nenabled=false\n"
    )
    m = load_pii_map(_write(tmp_path, body))
    assert set(m.entities) == {"on"}


def test_parked_duplicate_still_rejected(tmp_path: Path) -> None:
    # A name must be unique even when parked — a parked dup is still a config bug.
    body = (
        "map_version='v'\n[density]\nrestricted_at=3\nclassified_at=5\n"
        "[[entities]]\nname='dup'\ntier_floor='normal'\n"
        "[[entities]]\nname='dup'\ntier_floor='normal'\nenabled=false\n"
    )
    with pytest.raises(ValueError, match="duplicate PII entity"):
        load_pii_map(_write(tmp_path, body))
