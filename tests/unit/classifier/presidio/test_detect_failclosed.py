"""detect(): the §0 fail-closed paths + the success path, without a real jail.

The jailed NER pass needs nsjail + the extract venv + spaCy models (an
integration smoke covers that). Here we monkeypatch the chokepoint so the
orchestration — venv-absent, jail-failure, bad-output, and the happy mapping
path — is fully unit-tested. Under-classification is the one catastrophic error
(CLASSIFIER_PLAN §0), so every failure MUST pin the floor to CLASSIFIED.
"""

from __future__ import annotations

import pytest

from eyenet.classifier.presidio import detect, load_pii_map
from eyenet.classifier.sandbox import ExtractResult, FailedClosed, FailReason, stdlib_profile
from eyenet.contracts.enums import SensitivityTier

pytestmark = pytest.mark.unit

_DETECT = "eyenet.classifier.presidio._detect"


def test_venv_unavailable_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(f"{_DETECT}.venv_profile", lambda: None)
    verdict = detect("any text")
    assert verdict.fail_closed is True
    assert verdict.tier_floor is SensitivityTier.CLASSIFIED
    assert verdict.matches == ()


def test_jail_failure_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(f"{_DETECT}.venv_profile", stdlib_profile)
    monkeypatch.setattr(
        f"{_DETECT}.extract_sandboxed",
        lambda blob, **kw: FailedClosed(reason=FailReason.PARSER_KILLED, detail="SIGSYS"),
    )
    verdict = detect("any text")
    assert verdict.fail_closed is True
    assert verdict.tier_floor is SensitivityTier.CLASSIFIED


def test_bad_envelope_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    # Clean jail exit but no findings list in meta -> fail closed, not NORMAL.
    monkeypatch.setattr(f"{_DETECT}.venv_profile", stdlib_profile)
    monkeypatch.setattr(
        f"{_DETECT}.extract_sandboxed",
        lambda blob, **kw: ExtractResult(text="", meta={"analyzer": "x"}),
    )
    verdict = detect("any text")
    assert verdict.fail_closed is True
    assert verdict.tier_floor is SensitivityTier.CLASSIFIED


def test_malformed_finding_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    # A findings entry missing required keys is garbage -> fail closed.
    monkeypatch.setattr(f"{_DETECT}.venv_profile", stdlib_profile)
    monkeypatch.setattr(
        f"{_DETECT}.extract_sandboxed",
        lambda blob, **kw: ExtractResult(text="", meta={"findings": [{"entity_type": "PERSON"}]}),
    )
    assert detect("any text").fail_closed is True


def test_non_dict_finding_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    # A findings list whose entries are not objects is garbage -> fail closed.
    monkeypatch.setattr(f"{_DETECT}.venv_profile", stdlib_profile)
    monkeypatch.setattr(
        f"{_DETECT}.extract_sandboxed",
        lambda blob, **kw: ExtractResult(text="", meta={"findings": ["not-an-object"]}),
    )
    assert detect("any text").fail_closed is True


def test_success_path_maps_findings(monkeypatch: pytest.MonkeyPatch) -> None:
    finding = {
        "entity_type": "US_SSN",
        "start": 4,
        "end": 15,
        "score": 0.95,
        "language": "en",
        "text": "123-45-6789",
    }
    monkeypatch.setattr(f"{_DETECT}.venv_profile", stdlib_profile)
    monkeypatch.setattr(
        f"{_DETECT}.extract_sandboxed",
        lambda blob, **kw: ExtractResult(text="", meta={"findings": [finding]}),
    )
    verdict = detect("ssn 123-45-6789")  # bundled map: US_SSN -> classified
    assert verdict.fail_closed is False
    assert verdict.tier_floor is SensitivityTier.CLASSIFIED
    assert [m.entity_type for m in verdict.matches] == ["US_SSN"]
    assert verdict.matches[0].matched_text == "123-45-6789"


def test_explicit_pii_map_version_flows_through(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(f"{_DETECT}.venv_profile", stdlib_profile)
    monkeypatch.setattr(
        f"{_DETECT}.extract_sandboxed",
        lambda blob, **kw: ExtractResult(text="", meta={"findings": []}),
    )
    pii_map = load_pii_map()
    verdict = detect("text", pii_map=pii_map)
    assert verdict.fail_closed is False
    assert verdict.map_version == pii_map.map_version
    assert verdict.tier_floor is SensitivityTier.NORMAL
