"""End-to-end containment proof against the real nsjail binary.

Skipped where nsjail is absent. These are the tests that actually prove the
cage holds — the unit suite verifies the decision logic with fakes; this
verifies the kernel-level isolation on the host EYENET will run on.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from eyenet.classifier.sandbox import (
    _chokepoint as cp,
    arm_sandbox,
    extract_sandboxed,
    verify_sandbox,
)
from eyenet.classifier.sandbox._policy import SandboxLimits
from eyenet.classifier.sandbox._types import ExtractResult, FailedClosed, FailReason

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(shutil.which("nsjail") is None, reason="nsjail not installed"),
]

# Snappy limits keep the timeout/kill tests fast while staying valid.
_FAST = SandboxLimits(time_limit_s=2, parent_timeout_s=4)


@pytest.fixture(autouse=True)
def _clean_gate() -> Iterator[None]:
    cp.reset_sandbox()
    yield
    cp.reset_sandbox()


def _worker(tmp_path: Path, src: str) -> str:
    path = tmp_path / "worker.py"
    path.write_text(src)
    return str(path)


# An echo worker: read the bound input, emit the envelope. Stdlib only.
_ECHO = (
    "import json\n"
    'data = open("/input", "rb").read()\n'
    'print(json.dumps({"text": data.decode("utf-8", "replace"), "meta": {"len": len(data)}}))\n'
)


def test_real_canary_proves_containment() -> None:
    v = verify_sandbox(limits=_FAST)
    assert v.ok, v.failure_reason
    assert v.benign_ok
    assert len(v.probes) == 4
    for probe in v.probes:
        assert probe.contained, f"{probe.probe} escaped: {probe.detail}"


def test_real_arm_sets_healthy() -> None:
    v = arm_sandbox(limits=_FAST, force=True)
    assert v.ok and cp.sandbox_state() is cp.SandboxState.HEALTHY


def test_real_extract_roundtrip(tmp_path: Path) -> None:
    arm_sandbox(limits=_FAST, force=True)
    worker = _worker(tmp_path, _ECHO)
    res = extract_sandboxed(b"classified dossier", worker_path=worker, limits=_FAST)
    assert isinstance(res, ExtractResult)
    assert res.text == "classified dossier"
    assert res.meta["len"] == 18


def test_real_parser_crash_fails_closed(tmp_path: Path) -> None:
    arm_sandbox(limits=_FAST, force=True)
    worker = _worker(tmp_path, "import sys\nsys.exit(3)\n")
    res = extract_sandboxed(b"x", worker_path=worker, limits=_FAST)
    assert isinstance(res, FailedClosed) and res.reason is FailReason.PARSER_CRASH


def test_real_spawn_attempt_is_killed(tmp_path: Path) -> None:
    arm_sandbox(limits=_FAST, force=True)
    # A malicious parser trying to spawn a child trips the seccomp KILL (no clone).
    worker = _worker(
        tmp_path,
        "import subprocess\nsubprocess.run(['/usr/bin/id'])\nprint('{\"text\":\"\"}')\n",
    )
    res = extract_sandboxed(b"x", worker_path=worker, limits=_FAST)
    assert isinstance(res, FailedClosed) and res.reason is FailReason.PARSER_KILLED


def test_real_runaway_is_stopped(tmp_path: Path) -> None:
    arm_sandbox(limits=_FAST, force=True)
    worker = _worker(tmp_path, 'import time\ntime.sleep(60)\nprint(\'{"text":""}\')\n')
    res = extract_sandboxed(b"x", worker_path=worker, limits=_FAST)
    assert isinstance(res, FailedClosed)
    # nsjail's wall-clock kill (SIGKILL) or the parent backstop — both contained.
    assert res.reason in (FailReason.TIMEOUT, FailReason.PARSER_KILLED)


def test_real_output_bomb_is_bounded(tmp_path: Path) -> None:
    arm_sandbox(limits=_FAST, force=True)
    worker = _worker(tmp_path, "import sys\nsys.stdout.write('A' * 5_000_000)\n")
    limits = SandboxLimits(time_limit_s=2, parent_timeout_s=4, max_stdout_bytes=1024)
    res = extract_sandboxed(b"x", worker_path=worker, limits=limits)
    assert isinstance(res, FailedClosed) and res.reason is FailReason.OUTPUT_OVERFLOW
