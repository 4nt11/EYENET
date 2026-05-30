"""Chokepoint: envelope decode, outcome mapping, and the arm/degrade gate."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from eyenet.classifier.sandbox import _chokepoint as cp
from eyenet.classifier.sandbox._types import (
    ExtractResult,
    FailedClosed,
    FailReason,
    SandboxOutcome,
    SandboxStatus,
    SandboxVerification,
)

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clean_gate() -> Iterator[None]:
    cp.reset_sandbox()
    yield
    cp.reset_sandbox()


def _verification(ok: bool) -> SandboxVerification:
    return SandboxVerification(
        ok=ok,
        nsjail_path="/usr/local/bin/nsjail" if ok else None,
        nsjail_version=None,
        benign_ok=ok,
        probes=(),
        failure_reason=None if ok else "uncontained probes: spawn",
    )


def _outcome(status: SandboxStatus, *, stdout: bytes = b"") -> SandboxOutcome:
    return SandboxOutcome(
        status=status,
        exit_code=0 if status is SandboxStatus.OK else 1,
        signal=31 if status is SandboxStatus.KILLED_SIGNAL else None,
        stdout=stdout,
        stderr_tail="",
        duration_s=0.01,
        truncated=False,
    )


# ---- _parse_envelope ------------------------------------------------------


def test_envelope_valid_with_meta() -> None:
    res = cp._parse_envelope(b'{"text":"hello","meta":{"pages":2}}')
    assert isinstance(res, ExtractResult)
    assert res.text == "hello" and res.meta == {"pages": 2}


def test_envelope_text_only_defaults_meta() -> None:
    res = cp._parse_envelope(b'{"text":"hi"}')
    assert isinstance(res, ExtractResult) and res.meta == {}


@pytest.mark.parametrize(
    "raw",
    [
        b"not json",
        b'["list","not","object"]',
        b'{"meta":{}}',  # missing text
        b'{"text":5}',  # text not a string
        b'{"text":"x","meta":[]}',  # meta not an object
        b"\xff\xfe",  # not utf-8
    ],
)
def test_envelope_malformed_returns_none(raw: bytes) -> None:
    assert cp._parse_envelope(raw) is None


# ---- _interpret_extraction ------------------------------------------------


def test_interpret_ok_valid_envelope() -> None:
    res = cp._interpret_extraction(_outcome(SandboxStatus.OK, stdout=b'{"text":"x"}'))
    assert isinstance(res, ExtractResult) and res.text == "x"


def test_interpret_ok_garbage_is_bad_output() -> None:
    res = cp._interpret_extraction(_outcome(SandboxStatus.OK, stdout=b"garbage"))
    assert isinstance(res, FailedClosed) and res.reason is FailReason.BAD_OUTPUT


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (SandboxStatus.LAUNCH_FAILED, FailReason.LAUNCH_FAILED),
        (SandboxStatus.NONZERO_EXIT, FailReason.PARSER_CRASH),
        (SandboxStatus.KILLED_SIGNAL, FailReason.PARSER_KILLED),
        (SandboxStatus.TIMEOUT, FailReason.TIMEOUT),
        (SandboxStatus.OUTPUT_OVERFLOW, FailReason.OUTPUT_OVERFLOW),
    ],
)
def test_interpret_non_ok_maps_to_reason(status: SandboxStatus, reason: FailReason) -> None:
    res = cp._interpret_extraction(_outcome(status))
    assert isinstance(res, FailedClosed) and res.reason is reason


# ---- arm / degrade gate ---------------------------------------------------


def test_arm_healthy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cp, "verify_sandbox", lambda **_k: _verification(True))
    v = cp.arm_sandbox()
    assert v.ok and cp.sandbox_state() is cp.SandboxState.HEALTHY
    assert cp.current_verification() is v


def test_arm_degraded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cp, "verify_sandbox", lambda **_k: _verification(False))
    v = cp.arm_sandbox()
    assert not v.ok and cp.sandbox_state() is cp.SandboxState.DEGRADED


def test_arm_is_idempotent_then_force_reruns(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    monkeypatch.setattr(
        cp, "verify_sandbox", lambda **_k: (calls.append(1), _verification(True))[1]
    )
    cp.arm_sandbox()
    cp.arm_sandbox()
    assert len(calls) == 1  # cached
    cp.arm_sandbox(force=True)
    assert len(calls) == 2  # re-proved


def test_extract_refused_when_unarmed() -> None:
    res = cp.extract_sandboxed(b"data", worker_path="worker.py")
    assert isinstance(res, FailedClosed) and res.reason is FailReason.SANDBOX_DEGRADED


def test_extract_refused_when_degraded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cp, "verify_sandbox", lambda **_k: _verification(False))
    cp.arm_sandbox()
    res = cp.extract_sandboxed(b"data", worker_path="worker.py")
    assert isinstance(res, FailedClosed) and res.reason is FailReason.SANDBOX_DEGRADED


def test_extract_healthy_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cp, "verify_sandbox", lambda **_k: _verification(True))
    cp.arm_sandbox()

    seen: dict[str, object] = {}

    def fake_run(**kw: object) -> SandboxOutcome:
        seen.update(kw)
        # prove the blob was delivered to the per-parse input file
        with open(str(kw["input_path"]), "rb") as fh:
            seen["delivered"] = fh.read()
        return _outcome(SandboxStatus.OK, stdout=b'{"text":"extracted","meta":{"n":1}}')

    monkeypatch.setattr(cp, "run_sandboxed", fake_run)
    res = cp.extract_sandboxed(b"hostile-bytes", worker_path="worker.py", worker_args=("pdf",))
    assert isinstance(res, ExtractResult) and res.text == "extracted"
    assert seen["nsjail_path"] == "/usr/local/bin/nsjail"
    assert seen["delivered"] == b"hostile-bytes"
    assert seen["worker_args"] == ("pdf",)


def test_extract_healthy_failedclosed_on_kill(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cp, "verify_sandbox", lambda **_k: _verification(True))
    cp.arm_sandbox()
    monkeypatch.setattr(cp, "run_sandboxed", lambda **_k: _outcome(SandboxStatus.KILLED_SIGNAL))
    res = cp.extract_sandboxed(b"x", worker_path="worker.py")
    assert isinstance(res, FailedClosed) and res.reason is FailReason.PARSER_KILLED
