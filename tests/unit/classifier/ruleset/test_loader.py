"""Ruleset loader: strict shape, eager fail-closed compile, env override."""

from __future__ import annotations

from pathlib import Path

import pytest

from eyenet.classifier.ruleset import CompiledRuleset, load_ruleset
from eyenet.classifier.ruleset._loader import RULESET_ENV
from eyenet.contracts.enums import SensitivityTier

pytestmark = pytest.mark.unit


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "rules.toml"
    path.write_text(body, "utf-8")
    return path


# ---- bundled default -------------------------------------------------------


def test_bundled_default_loads_and_compiles() -> None:
    rs = load_ruleset()
    assert isinstance(rs, CompiledRuleset)
    assert rs.version == "v3"
    names = {r.name for r in rs.rules}
    # spine categories must all be present
    assert {
        "secret_private_key_pem",
        "pii_us_ssn",
        "onion_address",
        "banner_en",
        "banner_es",
        "banner_zh",
        "struct_portion_marking",
    } <= names
    # every bundled rule carries a real tier and a compiled pattern
    for rule in rs.rules:
        assert isinstance(rule.tier_floor, SensitivityTier)
        assert hasattr(rule.pattern, "finditer")


def test_bundled_banners_carry_lang() -> None:
    rs = load_ruleset()
    by_name = {r.name: r for r in rs.rules}
    assert by_name["banner_en"].lang == "en"
    assert by_name["banner_es"].lang == "es"
    assert by_name["pii_us_ssn"].lang == "en"


# ---- path / env resolution -------------------------------------------------


def test_explicit_path_overrides_default(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "ruleset_version = 'custom'\n[[rules]]\nname='x'\npattern='foo'\ntier_floor='restricted'\n",
    )
    rs = load_ruleset(path)
    assert rs.version == "custom"
    assert [r.name for r in rs.rules] == ["x"]


def test_env_override_used_when_no_arg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _write(
        tmp_path,
        "ruleset_version = 'env'\n[[rules]]\nname='y'\npattern='bar'\ntier_floor='normal'\n",
    )
    monkeypatch.setenv(RULESET_ENV, str(path))
    rs = load_ruleset()
    assert rs.version == "env"


def test_explicit_arg_beats_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_file = _write(
        tmp_path,
        "ruleset_version = 'env'\n[[rules]]\nname='y'\npattern='bar'\ntier_floor='normal'\n",
    )
    arg_file = tmp_path / "arg.toml"
    arg_file.write_text(
        "ruleset_version = 'arg'\n[[rules]]\nname='z'\npattern='baz'\ntier_floor='normal'\n",
        "utf-8",
    )
    monkeypatch.setenv(RULESET_ENV, str(env_file))
    assert load_ruleset(arg_file).version == "arg"


def test_missing_file_raises_filenotfound(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_ruleset(tmp_path / "nope.toml")


# ---- fail-closed validation ------------------------------------------------


def test_unknown_key_rejected(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "ruleset_version='v'\n[[rules]]\nname='a'\npattern='x'\ntier_floor='normal'\nbogus=1\n",
    )
    with pytest.raises(ValueError, match="Extra inputs"):  # pydantic extra='forbid'
        load_ruleset(path)


def test_bad_tier_rejected(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "ruleset_version='v'\n[[rules]]\nname='a'\npattern='x'\ntier_floor='ultra'\n",
    )
    with pytest.raises(ValueError, match="Input should be"):
        load_ruleset(path)


def test_uncompilable_pattern_fails_at_load(tmp_path: Path) -> None:
    # An unbalanced group never compiles — must fail at LOAD, not at classify.
    path = _write(
        tmp_path,
        "ruleset_version='v'\n[[rules]]\nname='broken'\npattern='(unclosed'\ntier_floor='restricted'\n",
    )
    with pytest.raises(ValueError, match="does not compile under RE2"):
        load_ruleset(path)


@pytest.mark.parametrize("pattern", ["(?<=foo)bar", "foo(?=bar)", r"(\w)\1"])
def test_lookaround_and_backref_rejected(tmp_path: Path, pattern: str) -> None:
    # RE2 has no lookaround / backreferences by construction; such a rule must be
    # refused at load rather than silently dropped (which would under-classify).
    path = _write(
        tmp_path,
        f"ruleset_version='v'\n[[rules]]\nname='r'\npattern='{pattern}'\ntier_floor='classified'\n",
    )
    with pytest.raises(ValueError, match="does not compile under RE2"):
        load_ruleset(path)


def test_duplicate_rule_name_rejected(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "ruleset_version='v'\n"
        "[[rules]]\nname='dup'\npattern='a'\ntier_floor='normal'\n"
        "[[rules]]\nname='dup'\npattern='b'\ntier_floor='normal'\n",
    )
    with pytest.raises(ValueError, match="duplicate rule name"):
        load_ruleset(path)


def test_literal_string_backslash_survives(tmp_path: Path) -> None:
    # A TOML literal string passes '\d' through verbatim; the rule must match a
    # digit run, proving the escape was not mangled into a backspace etc.
    path = _write(
        tmp_path,
        "ruleset_version='v'\n[[rules]]\nname='digits'\npattern='\\d{4}'\ntier_floor='restricted'\n",
    )
    rs = load_ruleset(path)
    assert list(rs.rules[0].pattern.finditer("year 2026")), "literal \\d must match digits"


# ---- enabled flag (parked rules) -------------------------------------------


def test_disabled_rule_excluded_from_compiled(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "ruleset_version='v'\n"
        "[[rules]]\nname='on'\npattern='foo'\ntier_floor='restricted'\n"
        "[[rules]]\nname='off'\npattern='bar'\ntier_floor='restricted'\nenabled=false\n",
    )
    rs = load_ruleset(path)
    assert [r.name for r in rs.rules] == ["on"]  # parked rule not compiled in


def test_disabled_rule_with_bad_pattern_does_not_fail_load(tmp_path: Path) -> None:
    # A parked rule is never compiled, so an as-yet-invalid pattern must NOT
    # refuse the whole ruleset — that is the point of parking.
    path = _write(
        tmp_path,
        "ruleset_version='v'\n"
        "[[rules]]\nname='ok'\npattern='foo'\ntier_floor='restricted'\n"
        "[[rules]]\nname='parked'\npattern='(?<=x)y'\ntier_floor='restricted'\nenabled=false\n",
    )
    rs = load_ruleset(path)  # must not raise despite the lookaround in 'parked'
    assert [r.name for r in rs.rules] == ["ok"]


def test_bundled_default_parks_fp_catastrophic_rules() -> None:
    names = {r.name for r in load_ruleset().rules}
    # bare-number / email / phone shapes collapse NORMAL — must ship parked
    assert {"pii_co_cedula", "pii_email", "pii_phone_intl", "pii_ar_dni_cuit"}.isdisjoint(names)
