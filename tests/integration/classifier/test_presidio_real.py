"""Real-jail smoke for the Presidio stage (slice 4): text -> jailed NER -> floor.

Unlike the unit tests (which feed synthetic findings straight to the mapper),
this drives the WHOLE jailed pass: the extracted text goes through the chokepoint
to ``presidio_worker.py`` in the eyenet-extract venv, which runs presidio +
spaCy in BOTH es and en, and the findings come back as a tier-floor verdict.

Gated like the rest of the real-jail suite: nsjail + the eyenet-extract venv +
both spaCy models (es_core_news_sm, en_core_web_sm) + presidio_analyzer. Absent
any of those, the smoke skips; the pure unit suite already proves the decision
logic and the §0 fail-closed seam.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator

import pytest

from eyenet.classifier.presidio import detect
from eyenet.classifier.sandbox import (
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
_SITE = venv_site_packages(_VENV) if _VENV is not None else None
_HAVE_DEPS = _SITE is not None and all(
    (_SITE / pkg).exists() for pkg in ("presidio_analyzer", "es_core_news_sm", "en_core_web_sm")
)
_needs_presidio = pytest.mark.skipif(
    not _HAVE_DEPS, reason="eyenet-extract venv lacks presidio + es/en spaCy models"
)

# Arm the canary with small limits (the probes are stdlib-light); detect() passes
# its own presidio-sized budget per call.
_ARM_LIMITS = SandboxLimits(time_limit_s=15, parent_timeout_s=20)
_NER_LIMITS = SandboxLimits(
    rlimit_as_mb=2048, rlimit_cpu_s=55, time_limit_s=50, parent_timeout_s=60
)


@pytest.fixture(autouse=True)
def _armed() -> Iterator[None]:
    reset_sandbox()
    arm_sandbox(limits=_ARM_LIMITS, force=True)
    assert sandbox_state() is cp.SandboxState.HEALTHY
    yield
    reset_sandbox()


@_needs_presidio
def test_spanish_ner_completes() -> None:
    # Spanish NER runs end-to-end in the jail (no email/URL → no network
    # recognizer; see test_network_recognizer_path_fails_closed for that path).
    text = "Estimado equipo, el informe sobre Juan Pérez y María González ya está listo."
    verdict = detect(text, limits=_NER_LIMITS)
    assert verdict.fail_closed is False, "es NER should complete in-jail"
    assert any(m.entity_type == "PERSON" and m.language == "es" for m in verdict.matches)


@_needs_presidio
def test_email_detected_without_network() -> None:
    # Regression guard for the tldextract landmine: presidio's EmailRecognizer
    # validates an email's TLD via tldextract, whose default REFRESHES the public
    # suffix list over HTTP. In the jail (read-only cache, no /etc, no route) that
    # fetch's DNS lookup made glibc spawn a resolver thread (clone3) -> the
    # no-spawn seccomp policy KILLed it -> the whole pass failed closed. The worker
    # forces tldextract offline (bundled snapshot), so the email is detected with
    # ZERO network and ZERO threads. Must complete (not fail closed) AND find the
    # email -> RESTRICTED. If this regresses to fail_closed, the offline override
    # broke.
    text = "Contacto operativo: juan.perez@example.net"
    verdict = detect(text, limits=_NER_LIMITS)
    assert verdict.fail_closed is False, "tldextract offline override must keep the pass alive"
    assert any(m.entity_type == "EMAIL_ADDRESS" for m in verdict.matches)
    assert verdict.tier_floor is SensitivityTier.RESTRICTED


@_needs_presidio
def test_english_engine_contributes() -> None:
    # An English sentence the es NER would under-detect — proves the en pass runs
    # (the ES+EN MAX is the fail-closed-correct choice for multilingual evidence).
    text = "Dr. Margaret Hamilton met General Eisenhower in Washington last Tuesday."
    verdict = detect(text, limits=_NER_LIMITS)
    assert verdict.fail_closed is False
    assert any(m.language == "en" for m in verdict.matches), "the en engine must produce findings"


@_needs_presidio
def test_memory_starved_pass_fails_closed() -> None:
    # A budget too small to even load the spaCy models -> the jail kills the
    # worker -> §0 fail-closed to CLASSIFIED. Containment, not a benign NORMAL.
    starved = SandboxLimits(rlimit_as_mb=64, time_limit_s=10, parent_timeout_s=15)
    verdict = detect("Juan Pérez, juan@example.net", limits=starved)
    assert verdict.fail_closed is True
    assert verdict.tier_floor is SensitivityTier.CLASSIFIED
