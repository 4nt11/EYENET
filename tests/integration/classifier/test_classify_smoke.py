"""Cross-slice smoke test: real docx -> extract (slice 2) -> classify (slice 3).

Unlike the unit tests (which feed text straight to ``classify``), this drives the
WHOLE deterministic path on a real, diverse-producer document: a fictional
intelligence memo dense with classification banners and portion markings. It is
the regression anchor for the gap the fixture first exposed — a body carrying
portion markings (``(TS//NH//NF)``) must reach CLASSIFIED, never NORMAL.

The fixture is explicitly marked "FICTIONAL TEST FIXTURE — NOT A REAL CLASSIFIED
DOCUMENT"; all agencies/codewords/personnel in it are invented for testing.

Gated like the rest of the real-jail suite: nsjail + the ``eyenet-extract`` venv
(docx needs python-docx).
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from eyenet.classifier.extract import extract_document
from eyenet.classifier.ruleset import classify, load_ruleset
from eyenet.classifier.sandbox import (
    ExtractResult,
    SandboxLimits,
    _chokepoint as cp,
    arm_sandbox,
    reset_sandbox,
    resolve_extract_venv,
    sandbox_state,
)
from eyenet.classifier.sandbox._profiles import venv_site_packages
from eyenet.contracts.enums import SensitivityTier

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(shutil.which("nsjail") is None, reason="nsjail not installed"),
]

_VENV = resolve_extract_venv()
_HAVE_VENV = _VENV is not None and venv_site_packages(_VENV) is not None
_needs_venv = pytest.mark.skipif(not _HAVE_VENV, reason="eyenet-extract venv not built")

_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "classifier"
    / "classified_memo_fictional.docx"
)
_LIMITS = SandboxLimits(time_limit_s=15, parent_timeout_s=20)


@pytest.fixture(autouse=True)
def _armed() -> Iterator[None]:
    reset_sandbox()
    arm_sandbox(limits=_LIMITS, force=True)
    assert sandbox_state() is cp.SandboxState.HEALTHY
    yield
    reset_sandbox()


@_needs_venv
def test_classified_memo_extracts_and_classifies() -> None:
    blob = _FIXTURE.read_bytes()

    result = extract_document(blob, limits=_LIMITS)
    assert isinstance(result, ExtractResult), result
    assert result.meta["doc_kind"] == "zip_ooxml"
    assert result.meta["empty"] is False

    verdict = classify(result.text, load_ruleset())
    assert verdict.tier_floor is SensitivityTier.CLASSIFIED
    fired = {m.rule_name for m in verdict.matches}
    # both the plaintext banners AND the structured portion markings must fire
    assert "banner_en" in fired
    assert "portion_marking" in fired
