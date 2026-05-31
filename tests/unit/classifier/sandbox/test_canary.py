"""Canary verdict logic + boot verification, with an injected fake jail."""

from __future__ import annotations

import hashlib

import pytest

from eyenet.classifier.sandbox._canary import (
    _BENIGN_INPUT,
    _BENIGN_MARKER,
    _benign_ok,
    _interpret_probe,
    discover_nsjail,
    verify_sandbox,
)
from eyenet.classifier.sandbox._types import SandboxOutcome, SandboxStatus

pytestmark = pytest.mark.unit

_BENIGN_STDOUT = (_BENIGN_MARKER + hashlib.sha256(_BENIGN_INPUT).hexdigest()).encode()


def _outcome(
    status: SandboxStatus,
    *,
    stdout: bytes = b"",
    signal: int | None = None,
    stderr: str = "",
) -> SandboxOutcome:
    return SandboxOutcome(
        status=status,
        exit_code=0 if status is SandboxStatus.OK else None,
        signal=signal,
        stdout=stdout,
        stderr_tail=stderr,
        duration_s=0.01,
        truncated=False,
    )


# ---- _interpret_probe -----------------------------------------------------


def test_probe_launch_failure_is_not_contained() -> None:
    res = _interpret_probe("network", _outcome(SandboxStatus.LAUNCH_FAILED, stderr="boom"))
    assert not res.contained and "launch failed" in res.detail


def test_probe_escape_is_not_contained() -> None:
    res = _interpret_probe("network", _outcome(SandboxStatus.OK, stdout=b"VERDICT=ESCAPED net"))
    assert not res.contained and "ESCAPED" in res.detail


def test_probe_killed_is_contained() -> None:
    res = _interpret_probe("spawn", _outcome(SandboxStatus.KILLED_SIGNAL, signal=31))
    assert res.contained and "killed by jail" in res.detail


def test_probe_clean_denied_is_contained() -> None:
    res = _interpret_probe(
        "filesystem", _outcome(SandboxStatus.OK, stdout=b"VERDICT=denied:FileNotFoundError")
    )
    assert res.contained and "denied" in res.detail


# ---- _benign_ok -----------------------------------------------------------


def test_benign_ok_true_on_matching_hash() -> None:
    assert _benign_ok(_outcome(SandboxStatus.OK, stdout=_BENIGN_STDOUT))


def test_benign_ok_false_on_non_ok_status() -> None:
    assert not _benign_ok(_outcome(SandboxStatus.NONZERO_EXIT))


def test_benign_ok_false_on_wrong_hash() -> None:
    assert not _benign_ok(_outcome(SandboxStatus.OK, stdout=b"BENIGN_OK deadbeef"))


# ---- verify_sandbox (fake runner) -----------------------------------------


def _runner(*, escape: str | None = None, benign_ok: bool = True):
    def runner(**kw: object) -> SandboxOutcome:
        args = kw["worker_args"]
        if not args:  # the benign control
            return (
                _outcome(SandboxStatus.OK, stdout=_BENIGN_STDOUT)
                if benign_ok
                else _outcome(SandboxStatus.NONZERO_EXIT)
            )
        probe = args[0]  # type: ignore[index]
        if probe == escape:
            return _outcome(SandboxStatus.OK, stdout=b"VERDICT=ESCAPED")
        return _outcome(SandboxStatus.KILLED_SIGNAL, signal=31)

    return runner


def test_verify_passes_when_all_contained_and_benign_ok() -> None:
    v = verify_sandbox(nsjail_path="/usr/local/bin/nsjail", runner=_runner())
    assert v.ok and v.benign_ok
    assert len(v.probes) == 4 and all(p.contained for p in v.probes)
    assert v.failure_reason is None


def test_verify_fails_when_a_probe_escapes() -> None:
    v = verify_sandbox(nsjail_path="/n", runner=_runner(escape="spawn"))
    assert not v.ok and v.failure_reason is not None and "spawn" in v.failure_reason


def test_verify_fails_when_benign_control_fails() -> None:
    v = verify_sandbox(nsjail_path="/n", runner=_runner(benign_ok=False))
    assert not v.ok and "benign control" in (v.failure_reason or "")


def test_verify_fails_when_nsjail_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("eyenet.classifier.sandbox._canary.shutil.which", lambda _n: None)
    v = verify_sandbox()
    assert not v.ok and v.nsjail_path is None and "not found" in (v.failure_reason or "")


def test_discover_nsjail_returns_path_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("eyenet.classifier.sandbox._canary.shutil.which", lambda _n: "/bin/true")
    path, _version = discover_nsjail()
    assert path == "/bin/true"
