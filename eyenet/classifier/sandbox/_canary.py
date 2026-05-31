"""Boot-time containment proof.

Before the classifier trusts the sandbox to parse a hostile document, it runs a
deliberately-malicious *canary* THROUGH the real jail and demands that every
escape attempt be stopped — plus a benign control that must still succeed (a
cage so tight it breaks legitimate extraction is useless, not safe).

We never *assume* the sandbox works; we re-prove it on every arm. "Could not
prove isolation" is itself a fail-closed state: the classifier drops to degraded
mode where every document is classified at the highest tier.
"""

from __future__ import annotations

import hashlib
import shutil

# Version probe + jail launch only; controlled argv, shell=False.
import subprocess  # nosec B404
import tempfile
from collections.abc import Callable
from pathlib import Path

import structlog

from ._policy import DEFAULT_LIMITS, SandboxLimits
from ._runner import run_sandboxed
from ._types import CanaryProbeResult, SandboxOutcome, SandboxStatus, SandboxVerification

_log = structlog.get_logger()

# The hostile vectors, run one per jail invocation. Each must be DENIED (the op
# raised) or KILLED (the jail terminated the process). The only failing outcome
# is the worker reaching the escape and printing ESCAPED.
CANARY_PROBES: tuple[str, ...] = ("network", "spawn", "filesystem", "memory")

_ESCAPED = b"VERDICT=ESCAPED"
_BENIGN_MARKER = "BENIGN_OK "

# Self-contained, stdlib-only worker. Catches BaseException on purpose: this is
# throwaway adversarial probe code, and we want to report ANY form of denial.
_CANARY_SRC = """\
import sys

probe = sys.argv[1]


def verdict(token):
    print("VERDICT=" + token, flush=True)


if probe == "network":
    import socket
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        sock.connect(("1.1.1.1", 53))
        verdict("ESCAPED")
    except BaseException as exc:
        verdict("denied:" + type(exc).__name__)
elif probe == "spawn":
    import subprocess
    try:
        subprocess.run(["/usr/bin/id"], capture_output=True, timeout=3)
        verdict("ESCAPED")
    except BaseException as exc:
        verdict("denied:" + type(exc).__name__)
elif probe == "filesystem":
    try:
        with open("/etc/shadow", "rb") as handle:
            handle.read(1)
        verdict("ESCAPED")
    except BaseException as exc:
        verdict("denied:" + type(exc).__name__)
elif probe == "memory":
    verdict("alloc_start")
    buf = bytearray(8 * 1024 * 1024 * 1024)
    verdict("ESCAPED")
else:
    verdict("unknown_probe")
"""

# Benign control: read the bound input and echo its hash. Proves the jail can
# still perform a real extraction (input delivered RO, output returned).
_BENIGN_SRC = """\
import hashlib

data = open("/input", "rb").read()
print("BENIGN_OK " + hashlib.sha256(data).hexdigest(), flush=True)
"""

_BENIGN_INPUT = b"eyenet-sandbox-canary-control-input"

# Type of the run_sandboxed callable, so tests can inject a fake jail.
_Runner = Callable[..., SandboxOutcome]


def discover_nsjail() -> tuple[str | None, str | None]:
    """Locate nsjail and best-effort read its version. Never raises."""
    path = shutil.which("nsjail")
    if path is None:
        return None, None
    version: str | None = None
    try:
        # Resolved path, fixed args, shell=False.
        proc = subprocess.run(  # noqa: S603  # nosec B603
            [path, "--help"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        for line in (proc.stdout + proc.stderr).splitlines():
            if "version" in line.lower():
                version = line.strip()
                break
    except (OSError, subprocess.SubprocessError) as exc:
        _log.warning("sandbox.nsjail_version_probe_failed", error=str(exc))
    return path, version


def _interpret_probe(probe: str, outcome: SandboxOutcome) -> CanaryProbeResult:
    """Decide whether one hostile probe was contained. Pure; unit-tested."""
    if not outcome.launched:
        return CanaryProbeResult(
            probe=probe,
            contained=False,
            detail=f"jail launch failed: {outcome.stderr_tail[:200]}",
        )
    if _ESCAPED in outcome.stdout:
        return CanaryProbeResult(
            probe=probe,
            contained=False,
            detail=f"ESCAPED via {probe}: {outcome.stdout.decode('utf-8', 'replace')[:200]}",
        )
    if outcome.status is SandboxStatus.OK:
        # Clean exit without ESCAPED == the op was denied in-process.
        detail = outcome.stdout.decode("utf-8", "replace").strip() or "denied (clean exit)"
    else:
        detail = f"killed by jail: status={outcome.status.value} signal={outcome.signal}"
    return CanaryProbeResult(probe=probe, contained=True, detail=detail)


def _benign_ok(outcome: SandboxOutcome) -> bool:
    """The control extraction must exit cleanly and echo the right hash."""
    if outcome.status is not SandboxStatus.OK:
        return False
    expected = _BENIGN_MARKER + hashlib.sha256(_BENIGN_INPUT).hexdigest()
    return expected in outcome.stdout.decode("utf-8", "replace")


def verify_sandbox(
    *,
    nsjail_path: str | None = None,
    limits: SandboxLimits = DEFAULT_LIMITS,
    runner: _Runner = run_sandboxed,
) -> SandboxVerification:
    """Re-prove containment. Returns a verification whose ``ok`` arms normal mode.

    Writes the canary + benign workers to a private temp tree, runs each hostile
    probe and the benign control through ``runner`` (the real jail by default),
    and requires that every probe was contained AND the control succeeded.
    """
    resolved_path, version = (nsjail_path, None) if nsjail_path else discover_nsjail()
    if resolved_path is None:
        _log.error("sandbox.nsjail_absent")
        return SandboxVerification(
            ok=False,
            nsjail_path=None,
            nsjail_version=None,
            benign_ok=False,
            failure_reason="nsjail not found on PATH",
        )

    with tempfile.TemporaryDirectory(prefix="eyenet-canary-") as workdir:
        root = Path(workdir)
        canary_py = root / "canary.py"
        benign_py = root / "benign.py"
        benign_in = root / "input.bin"
        canary_py.write_text(_CANARY_SRC)
        benign_py.write_text(_BENIGN_SRC)
        benign_in.write_bytes(_BENIGN_INPUT)

        def _fresh_root(tag: str) -> str:
            d = root / f"jail-{tag}"
            d.mkdir()
            return str(d)

        probes: list[CanaryProbeResult] = []
        for probe in CANARY_PROBES:
            outcome = runner(
                nsjail_path=resolved_path,
                jail_root=_fresh_root(probe),
                worker_path=str(canary_py),
                input_path=None,
                limits=limits,
                worker_args=(probe,),
            )
            probes.append(_interpret_probe(probe, outcome))

        benign_outcome = runner(
            nsjail_path=resolved_path,
            jail_root=_fresh_root("benign"),
            worker_path=str(benign_py),
            input_path=str(benign_in),
            limits=limits,
            worker_args=(),
        )
        benign_ok = _benign_ok(benign_outcome)

    all_contained = all(p.contained for p in probes)
    ok = all_contained and benign_ok
    failure_reason: str | None = None
    if not ok:
        escaped = [p.probe for p in probes if not p.contained]
        parts: list[str] = []
        if escaped:
            parts.append(f"uncontained probes: {', '.join(escaped)}")
        if not benign_ok:
            parts.append("benign control extraction failed")
        failure_reason = "; ".join(parts)
        _log.error("sandbox.verification_failed", reason=failure_reason)
    else:
        _log.info("sandbox.verification_passed", nsjail=resolved_path)

    return SandboxVerification(
        ok=ok,
        nsjail_path=resolved_path,
        nsjail_version=version,
        benign_ok=benign_ok,
        probes=tuple(probes),
        failure_reason=failure_reason,
    )
