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
    assert verdict.ruleset_version == "v3"


def test_ssn_match_offsets_are_exact(default_ruleset: object) -> None:
    text = "subject ssn 123-45-6789 on file"
    verdict = _classify(text, default_ruleset)
    ssn = next(m for m in verdict.matches if m.rule_name == "pii_us_ssn")
    assert ssn.matched_text == "123-45-6789"
    assert text[ssn.start : ssn.end] == "123-45-6789"  # the spec's "offset N"
    assert ssn.tier_floor is SensitivityTier.RESTRICTED


def test_max_floor_over_mixed_matches(default_ruleset: object) -> None:
    # restricted (ssn) + classified (private key header) -> classified
    text = "123-45-6789\n-----BEGIN OPENSSH PRIVATE KEY-----"
    verdict = _classify(text, default_ruleset)
    fired = {m.rule_name for m in verdict.matches}
    assert {"pii_us_ssn", "secret_private_key_pem"} <= fired
    assert verdict.tier_floor is SensitivityTier.CLASSIFIED


def test_multiple_hits_each_get_provenance(default_ruleset: object) -> None:
    text = "111-22-3333 and 444-55-6666"
    verdict = _classify(text, default_ruleset)
    ssns = [m for m in verdict.matches if m.rule_name == "pii_us_ssn"]
    assert len(ssns) == 2
    assert [m.matched_text for m in ssns] == ["111-22-3333", "444-55-6666"]


def test_matches_sorted_by_offset(default_ruleset: object) -> None:
    text = "TOP SECRET\nsubject ssn 123-45-6789 follows"  # standalone banner + ssn
    verdict = _classify(text, default_ruleset)
    starts = [m.start for m in verdict.matches]
    assert len(starts) >= 2  # banner_en + pii_us_ssn
    assert starts == sorted(starts)


def test_portion_markings_catch_banner_less_fragment(default_ruleset: object) -> None:
    # A leaked body excerpt with portion markings but NO plaintext banner line
    # MUST NOT classify NORMAL — that is the catastrophic under-classification
    # direction (§0). This is the gap the DSR fixture exposed.
    frag = "(TS//NH//NF) Subsequent exploitation provided continuing access. (S//NF) Coverage held."
    verdict = _classify(frag, default_ruleset)
    fired = {m.rule_name for m in verdict.matches}
    assert "struct_portion_marking" in fired
    assert "banner_en" not in fired  # proves it was the portion marking, not a banner
    assert verdict.tier_floor is SensitivityTier.CLASSIFIED


def test_orcon_caveat_classified(default_ruleset: object) -> None:
    verdict = _classify("Dissemination is ORCON-controlled", default_ruleset)
    assert any(m.rule_name == "caveats_us_en" for m in verdict.matches)
    assert verdict.tier_floor is SensitivityTier.CLASSIFIED


def test_disabled_rule_does_not_fire(default_ruleset: object) -> None:
    # pii_email is parked (enabled=false) — an email alone must NOT raise the
    # floor (it would collapse NORMAL). Proves disabled rules are truly excluded.
    verdict = _classify("contact me at agent@example.net for details", default_ruleset)
    assert all(m.rule_name != "pii_email" for m in verdict.matches)
    assert verdict.tier_floor is SensitivityTier.NORMAL


def test_multilingual_banner_fires(default_ruleset: object) -> None:
    # RE2 handles non-Latin scripts via literal matching (no \b reliance).
    for text, name, lang in [
        ("文件标注为绝密", "banner_zh", "zh"),
        ("СОВЕРШЕННО СЕКРЕТНО", "banner_ru", "ru"),
    ]:
        verdict = _classify(text, default_ruleset)
        assert any(m.rule_name == name and m.lang == lang for m in verdict.matches), text
        assert verdict.tier_floor is SensitivityTier.CLASSIFIED


def test_banner_lang_recorded(default_ruleset: object) -> None:
    verdict = _classify("Marked TOP SECRET//NOFORN here", default_ruleset)
    banner = next(m for m in verdict.matches if m.rule_name == "banner_en")
    assert banner.lang == "en"
    assert verdict.tier_floor is SensitivityTier.CLASSIFIED


def test_spanish_banner_fires(default_ruleset: object) -> None:
    # Bare banner words fire only as a standalone-line stamp (see anchoring).
    verdict = _classify("CONFIDENCIAL\nDocumento del caso", default_ruleset)
    assert any(m.rule_name == "banner_es" and m.lang == "es" for m in verdict.matches)
    assert verdict.tier_floor is SensitivityTier.CLASSIFIED


def test_determinism_same_bytes_same_verdict(default_ruleset: object) -> None:
    text = "123-45-6789 0x" + "a" * 40 + " bc1qxy...not-real"
    first = _classify(text, default_ruleset)
    second = _classify(text, default_ruleset)
    assert first == second  # frozen dataclasses compare structurally


# ---- negative cases: classification WORDS in benign prose stay NORMAL ------
# The gap the unit suite originally lacked (and a 10-doc Gemini corpus exposed):
# banner/caveat words buried in ordinary prose must NOT raise the tier. Bare
# words fire only as standalone-line stamps; cross-language substring bleed
# (French bare SECRET matching English "secret") is gone.


@pytest.mark.parametrize(
    "text",
    [
        "Grandma's top secret recipe, a family secret passed down for years.",
        "This confidential report discusses classified information at length.",
        "He spoke about the focal point of the umbra during the eclipse.",
        "Les amis du restaurant ont reserve une table tres discrete ce soir.",
        "Personal data protected under the GDPR is stored securely on disk.",
        "The secret menu item is the worst-kept secret in town.",
    ],
)
def test_benign_prose_stays_normal(text: str, default_ruleset: object) -> None:
    assert _classify(text, default_ruleset).tier_floor is SensitivityTier.NORMAL


def test_standalone_banner_is_still_caught(default_ruleset: object) -> None:
    # Positive control: anchoring must not lose the real thing — a banner on its
    # own line still fires.
    verdict = _classify("UNIT 7 BRIEFING\nTOP SECRET\n\n1. Summary follows.", default_ruleset)
    assert any(m.rule_name == "banner_en" for m in verdict.matches)
    assert verdict.tier_floor is SensitivityTier.CLASSIFIED


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
    ssn = next(m for m in verdict.matches if m.rule_name == "pii_us_ssn")

    red = verdict.redacted()
    red_ssn = next(m for m in red.matches if m.rule_name == "pii_us_ssn")

    assert "123-45-6789" not in red_ssn.matched_text  # raw PII gone
    assert red_ssn.matched_text.endswith("6789")  # last-4 retained for review
    # offsets + identity + tier preserved — provenance intact
    assert (red_ssn.start, red_ssn.end, red_ssn.tier_floor) == (ssn.start, ssn.end, ssn.tier_floor)
    # original verdict is untouched (frozen, returns a copy)
    assert ssn.matched_text == "123-45-6789"
