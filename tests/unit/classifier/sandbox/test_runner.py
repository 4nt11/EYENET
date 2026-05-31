"""Runner internals: return-code classification, bounded drain, kill switch.

These exercise the parent-side guarantees WITHOUT spawning nsjail, using a
pipe-backed fake process. Real-jail end-to-end proof lives in the integration
suite.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import time

import pytest

from eyenet.classifier.sandbox._policy import SandboxLimits
from eyenet.classifier.sandbox._runner import (
    _drain_bounded,
    _kill_group,
    classify_returncode,
    run_sandboxed,
)
from eyenet.classifier.sandbox._types import SandboxStatus

pytestmark = pytest.mark.unit


class FakeProc:
    """A Popen stand-in backed by real OS pipes (so selectors work)."""

    def __init__(
        self,
        out: bytes = b"",
        err: bytes = b"",
        returncode: int = 0,
        *,
        close: bool = True,
        wait_raises: bool = False,
    ) -> None:
        self._or, self._ow = os.pipe()
        self._er, self._ew = os.pipe()
        if out:
            os.write(self._ow, out)
        if err:
            os.write(self._ew, err)
        self._open = not close
        if close:
            os.close(self._ow)
            os.close(self._ew)
        self.stdout = os.fdopen(self._or, "rb", buffering=0)
        self.stderr = os.fdopen(self._er, "rb", buffering=0)
        self.pid = 999999
        self._rc = returncode
        self.returncode: int | None = None
        self._wait_raises = wait_raises
        self._killed = False

    def wait(self, timeout: float | None = None) -> int:
        if self._wait_raises and not self._killed:
            raise subprocess.TimeoutExpired(cmd="nsjail", timeout=timeout or 0)
        self.returncode = -9 if self._killed else self._rc
        return self.returncode

    def kill(self) -> None:
        self._killed = True
        if self._open:
            for fd in (self._ow, self._ew):
                with contextlib.suppress(OSError):
                    os.close(fd)
            self._open = False


# ---- classify_returncode --------------------------------------------------


def test_classify_clean_exit() -> None:
    assert classify_returncode(0, "") == (SandboxStatus.OK, 0, None)


def test_classify_launch_marker_wins_over_code() -> None:
    status, code, sig = classify_returncode(255, "x Failed to build mount tree y")
    assert status is SandboxStatus.LAUNCH_FAILED and code is None and sig is None


def test_classify_signal_via_128_offset() -> None:
    # 159 == 128 + 31 (SIGSYS), nsjail's encoding of a seccomp kill.
    assert classify_returncode(159, "") == (SandboxStatus.KILLED_SIGNAL, None, 31)


def test_classify_negative_returncode_is_signal() -> None:
    assert classify_returncode(-9, "") == (SandboxStatus.KILLED_SIGNAL, None, 9)


def test_classify_nonzero_is_crash() -> None:
    assert classify_returncode(3, "") == (SandboxStatus.NONZERO_EXIT, 3, None)


# ---- _drain_bounded -------------------------------------------------------


def test_drain_reads_to_eof() -> None:
    proc = FakeProc(out=b"hello", err=b"warn")
    out, err, timed_out, overflowed = _drain_bounded(proc, SandboxLimits(), time.monotonic() + 30)
    assert out == b"hello"
    assert b"warn" in err
    assert not timed_out and not overflowed


def test_drain_caps_stdout_and_flags_overflow() -> None:
    proc = FakeProc(out=b"0123456789")
    limits = SandboxLimits(max_stdout_bytes=4)
    out, _err, _t, overflowed = _drain_bounded(proc, limits, time.monotonic() + 30)
    assert overflowed and len(out) <= 4


def test_drain_trims_stderr_to_tail() -> None:
    proc = FakeProc(out=b"", err=b"ABCDEFG")
    limits = SandboxLimits(max_stderr_bytes=3)
    _out, err, _t, _o = _drain_bounded(proc, limits, time.monotonic() + 30)
    assert err == b"EFG"


def test_drain_past_deadline_times_out_immediately() -> None:
    proc = FakeProc(out=b"x", close=False)  # pipes stay open (no EOF)
    out, _err, timed_out, _o = _drain_bounded(proc, SandboxLimits(), time.monotonic() - 1)
    assert timed_out and out == b""
    proc.kill()  # release the dangling write ends


# ---- run_sandboxed (Popen faked) ------------------------------------------


def _patch_popen(monkeypatch: pytest.MonkeyPatch, proc: FakeProc | Exception) -> None:
    def factory(*_args: object, **_kwargs: object) -> FakeProc:
        if isinstance(proc, Exception):
            raise proc
        return proc

    monkeypatch.setattr("eyenet.classifier.sandbox._runner.subprocess.Popen", factory)


def _run(monkeypatch: pytest.MonkeyPatch, proc: FakeProc | Exception, **kw: object):
    _patch_popen(monkeypatch, proc)
    return run_sandboxed(
        nsjail_path="/usr/local/bin/nsjail",
        jail_root="jailroot",
        worker_path="worker.py",
        input_path=None,
        limits=SandboxLimits(**kw),  # type: ignore[arg-type]
    )


def test_run_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    outcome = _run(monkeypatch, FakeProc(out=b'{"ok":1}', returncode=0))
    assert outcome.status is SandboxStatus.OK
    assert outcome.stdout == b'{"ok":1}'
    assert outcome.launched and not outcome.stopped_by_jail


def test_run_nonzero(monkeypatch: pytest.MonkeyPatch) -> None:
    outcome = _run(monkeypatch, FakeProc(returncode=4))
    assert outcome.status is SandboxStatus.NONZERO_EXIT
    assert outcome.exit_code == 4 and outcome.stopped_by_jail


def test_run_signalled(monkeypatch: pytest.MonkeyPatch) -> None:
    outcome = _run(monkeypatch, FakeProc(returncode=159))
    assert outcome.status is SandboxStatus.KILLED_SIGNAL and outcome.signal == 31


def test_run_launch_failed_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    outcome = _run(
        monkeypatch,
        FakeProc(err=b"[F] Couldn't prepare sandboxing policy", returncode=255),
    )
    assert outcome.status is SandboxStatus.LAUNCH_FAILED and not outcome.launched


def test_run_popen_filenotfound_is_launch_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    outcome = _run(monkeypatch, FileNotFoundError("no nsjail"))
    assert outcome.status is SandboxStatus.LAUNCH_FAILED


def test_run_overflow_kills_and_reports(monkeypatch: pytest.MonkeyPatch) -> None:
    outcome = _run(monkeypatch, FakeProc(out=b"x" * 100, returncode=0), max_stdout_bytes=8)
    assert outcome.status is SandboxStatus.OUTPUT_OVERFLOW and outcome.truncated


def test_run_parent_wait_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    # Streams EOF, but proc.wait() never returns -> parent timeout backstop fires.
    outcome = _run(monkeypatch, FakeProc(out=b"partial", wait_raises=True))
    assert outcome.status is SandboxStatus.TIMEOUT


def test_kill_group_survives_dead_pid() -> None:
    proc = FakeProc(out=b"", returncode=0)
    _kill_group(proc)  # pid 999999 does not exist -> ProcessLookupError suppressed
