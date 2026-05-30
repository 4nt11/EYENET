"""The one chokepoint. All hostile-byte parsing passes through here.

``extract_sandboxed`` is the *only* sanctioned way to turn an untrusted blob
into text. EYENET never imports a document parser into its own address space;
the parser runs as a stdlib-only worker inside the jail, and its output reaches
us as a bounded JSON envelope on stdout.

The chokepoint is armed by ``arm_sandbox``, which runs the boot canary
(:func:`verify_sandbox`). If the canary cannot prove containment — nsjail
absent, a probe escaped, or the benign control failed — the gate stays
**degraded**: every ``extract_sandboxed`` call returns :class:`FailedClosed`,
so every document is forced to the highest tier. Fail-closed by construction.
"""

from __future__ import annotations

import enum
import json
import tempfile
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from ._canary import verify_sandbox
from ._policy import DEFAULT_LIMITS, SandboxLimits
from ._runner import run_sandboxed
from ._types import (
    ExtractResult,
    FailedClosed,
    FailReason,
    SandboxOutcome,
    SandboxStatus,
    SandboxVerification,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

_log = structlog.get_logger()


class SandboxState(enum.Enum):
    """Operating mode of the extraction chokepoint."""

    UNARMED = "unarmed"  # never verified; extraction refused
    HEALTHY = "healthy"  # containment proven; normal extraction
    DEGRADED = "degraded"  # containment NOT proven; every doc -> fail closed


# Maps a non-OK sandbox status to the reason persisted in the fail-closed record.
_STATUS_TO_REASON: dict[SandboxStatus, FailReason] = {
    SandboxStatus.LAUNCH_FAILED: FailReason.LAUNCH_FAILED,
    SandboxStatus.NONZERO_EXIT: FailReason.PARSER_CRASH,
    SandboxStatus.KILLED_SIGNAL: FailReason.PARSER_KILLED,
    SandboxStatus.TIMEOUT: FailReason.TIMEOUT,
    SandboxStatus.OUTPUT_OVERFLOW: FailReason.OUTPUT_OVERFLOW,
}


class _Gate:
    """Process-wide armed state for the chokepoint. Read-mostly after arming."""

    def __init__(self) -> None:
        self._lock: threading.Lock = threading.Lock()
        self.state: SandboxState = SandboxState.UNARMED
        self.nsjail_path: str | None = None
        self.verification: SandboxVerification | None = None

    def lock_for_arm(self) -> threading.Lock:
        """The mutex guarding arm/reset transitions."""
        return self._lock


_GATE = _Gate()


def arm_sandbox(
    *, limits: SandboxLimits = DEFAULT_LIMITS, force: bool = False
) -> SandboxVerification:
    """Run the boot canary and arm (or degrade) the chokepoint.

    Idempotent: once armed HEALTHY it returns the cached verification unless
    ``force`` re-runs the proof. A failed proof sets DEGRADED — callers keep
    working, but every extraction fails closed until a successful re-arm.
    """
    with _GATE.lock_for_arm():
        if not force and _GATE.verification is not None:
            return _GATE.verification
        verification = verify_sandbox(limits=limits)
        _GATE.verification = verification
        if verification.ok:
            _GATE.state = SandboxState.HEALTHY
            _GATE.nsjail_path = verification.nsjail_path
            _log.info("sandbox.armed", state=_GATE.state.value)
        else:
            _GATE.state = SandboxState.DEGRADED
            _GATE.nsjail_path = None
            _log.error(
                "sandbox.degraded",
                reason=verification.failure_reason,
                hint="every document will be classified at the highest tier",
            )
        return verification


def sandbox_state() -> SandboxState:
    """Current operating mode of the chokepoint."""
    return _GATE.state


def current_verification() -> SandboxVerification | None:
    """The most recent canary verification, or None if never armed."""
    return _GATE.verification


def reset_sandbox() -> None:
    """Return the gate to UNARMED. Test-support only."""
    with _GATE.lock_for_arm():
        _GATE.state = SandboxState.UNARMED
        _GATE.nsjail_path = None
        _GATE.verification = None


def _parse_envelope(stdout: bytes) -> ExtractResult | None:
    """Decode a worker's ``{"text": str, "meta": object}`` stdout envelope.

    Returns None on any malformed output — an OK exit with garbage stdout is a
    fail-closed signal, not a benign empty document.
    """
    try:
        obj = json.loads(stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(obj, dict):
        return None
    text = obj.get("text")
    if not isinstance(text, str):
        return None
    meta = obj.get("meta", {})
    if not isinstance(meta, dict):
        return None
    return ExtractResult(text=text, meta=meta)


def _interpret_extraction(outcome: SandboxOutcome) -> ExtractResult | FailedClosed:
    """Turn a sandbox outcome into a trusted result or a reasoned fail-closed."""
    if outcome.status is SandboxStatus.OK:
        result = _parse_envelope(outcome.stdout)
        if result is None:
            return FailedClosed(
                reason=FailReason.BAD_OUTPUT,
                detail="worker exited 0 but emitted an unparseable envelope",
            )
        return result
    reason = _STATUS_TO_REASON.get(outcome.status, FailReason.PARSER_CRASH)
    return FailedClosed(
        reason=reason,
        detail=(
            f"status={outcome.status.value} exit={outcome.exit_code} "
            f"signal={outcome.signal} {outcome.stderr_tail[:200]}".strip()
        ),
    )


def extract_sandboxed(
    blob: bytes,
    *,
    worker_path: str,
    worker_args: Sequence[str] = (),
    limits: SandboxLimits = DEFAULT_LIMITS,
) -> ExtractResult | FailedClosed:
    """Extract text from an untrusted blob via the jailed worker.

    Returns :class:`ExtractResult` only on a clean jail exit with a valid
    envelope. Every other path — degraded gate, launch failure, crash, signal,
    timeout, output bomb, garbage output — returns :class:`FailedClosed`, which
    the classifier maps to the highest sensitivity tier plus an operator flag.
    """
    if _GATE.state is not SandboxState.HEALTHY or _GATE.nsjail_path is None:
        return FailedClosed(
            reason=FailReason.SANDBOX_DEGRADED,
            detail=f"chokepoint not armed (state={_GATE.state.value})",
        )

    with tempfile.TemporaryDirectory(prefix="eyenet-extract-") as workdir:
        root = Path(workdir)
        input_path = root / "input.bin"
        input_path.write_bytes(blob)
        jail_root = root / "jail"
        jail_root.mkdir()
        outcome = run_sandboxed(
            nsjail_path=_GATE.nsjail_path,
            jail_root=str(jail_root),
            worker_path=worker_path,
            input_path=str(input_path),
            limits=limits,
            worker_args=worker_args,
        )
    return _interpret_extraction(outcome)
