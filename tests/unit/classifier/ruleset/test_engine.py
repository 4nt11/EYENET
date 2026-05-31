"""classify(): deterministic MAX-floor verdict with per-match provenance."""

from __future__ import annotations

import unicodedata
from pathlib import Path

import pytest

from eyenet.classifier.ruleset import RegexVerdict, classify, load_ruleset
from eyenet.contracts.enums import SensitivityTier

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def default_ruleset() -> object:
    return load_ruleset()


def _classify(text: str, ruleset: object) -> RegexVerdict:
    return classify(text, ruleset)  # type: ignore[arg-type]


# ---- core behavior ---------------------------------------------------------


def test_no_match_is_normal_floor(default_ruleset: object) -> None:
    verdict = _classify("just some harmless prose with no markers", default_ruleset)
    assert verdict.tier_floor is SensitivityTier.NORMAL
    assert verdict.matches == ()
    assert verdict.engine == "re2"
    assert verdict.ruleset_version == "v1"


def test_ssn_match_offsets_are_exact(default_ruleset: object) -> None:
    text = "subject ssn 123-45-6789 on file"
    verdict = _classify(text, default_ruleset)
    ssn = next(m for m in verdict.matches if m.rule_name == "ssn_us")
    assert ssn.matched_text == "123-45-6789"
    assert text[ssn.start : ssn.end] == "123-45-6789"  # the spec's "offset N"
    assert ssn.tier_floor is SensitivityTier.RESTRICTED


def test_max_floor_over_mixed_matches(default_ruleset: object) -> None:
    # restricted (ssn) + classified (private key header) -> classified
    text = "123-45-6789\n-----BEGIN OPENSSH PRIVATE KEY-----"
    verdict = _classify(text, default_ruleset)
    fired = {m.rule_name for m in verdict.matches}
    assert {"ssn_us", "crypto_private_key"} <= fired
    assert verdict.tier_floor is SensitivityTier.CLASSIFIED


def test_multiple_hits_each_get_provenance(default_ruleset: object) -> None:
    text = "111-22-3333 and 444-55-6666"
    verdict = _classify(text, default_ruleset)
    ssns = [m for m in verdict.matches if m.rule_name == "ssn_us"]
    assert len(ssns) == 2
    assert [m.matched_text for m in ssns] == ["111-22-3333", "444-55-6666"]


def test_matches_sorted_by_offset(default_ruleset: object) -> None:
    text = "TOP SECRET banner then later an ssn 123-45-6789"
    verdict = _classify(text, default_ruleset)
    starts = [m.start for m in verdict.matches]
    assert starts == sorted(starts)


def test_banner_lang_recorded(default_ruleset: object) -> None:
    verdict = _classify("Marked TOP SECRET//NOFORN here", default_ruleset)
    banner = next(m for m in verdict.matches if m.rule_name == "banner_en")
    assert banner.lang == "en"
    assert verdict.tier_floor is SensitivityTier.CLASSIFIED


def test_spanish_banner_fires(default_ruleset: object) -> None:
    verdict = _classify("Documento CONFIDENCIAL del caso", default_ruleset)
    assert any(m.rule_name == "banner_es" and m.lang == "es" for m in verdict.matches)
    assert verdict.tier_floor is SensitivityTier.CLASSIFIED


def test_determinism_same_bytes_same_verdict(default_ruleset: object) -> None:
    text = "123-45-6789 0x" + "a" * 40 + " bc1qxy...not-real"
    first = _classify(text, default_ruleset)
    second = _classify(text, default_ruleset)
    assert first == second  # frozen dataclasses compare structurally


# ---- NFC normalization -----------------------------------------------------


def test_nfc_normalization_unifies_composed_forms(tmp_path: Path) -> None:
    # Rule pattern is NFC-composed "café"; input uses decomposed "e + ́".
    path = tmp_path / "r.toml"
    composed = unicodedata.normalize("NFC", "café")
    path.write_text(
        f"ruleset_version='v'\n[[rules]]\nname='cafe'\npattern='{composed}'\ntier_floor='restricted'\n",
        "utf-8",
    )
    ruleset = load_ruleset(path)
    decomposed = unicodedata.normalize("NFD", "the café here")
    assert decomposed != "the café here"  # genuinely decomposed input
    verdict = _classify(decomposed, ruleset)
    assert verdict.tier_floor is SensitivityTier.RESTRICTED


# ---- redaction -------------------------------------------------------------


def test_redacted_masks_span_but_keeps_provenance(default_ruleset: object) -> None:
    verdict = _classify("ssn 123-45-6789", default_ruleset)
    ssn = next(m for m in verdict.matches if m.rule_name == "ssn_us")

    red = verdict.redacted()
    red_ssn = next(m for m in red.matches if m.rule_name == "ssn_us")

    assert "123-45-6789" not in red_ssn.matched_text  # raw PII gone
    assert red_ssn.matched_text.endswith("6789")  # last-4 retained for review
    # offsets + identity + tier preserved — provenance intact
    assert (red_ssn.start, red_ssn.end, red_ssn.tier_floor) == (ssn.start, ssn.end, ssn.tier_floor)
    # original verdict is untouched (frozen, returns a copy)
    assert ssn.matched_text == "123-45-6789"
