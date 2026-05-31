"""Value types for the extraction sandbox — enums + frozen result records.

No logic lives here; these are the contract surface shared by the runner,
the canary verifier, and the chokepoint. Keeping them dependency-free makes
the decision logic in the other modules trivially unit-testable.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field


class SandboxStatus(enum.Enum):
    """How a single sandboxed run terminated.

    Everything that is not :attr:`OK` is a fail-closed signal for the caller:
    the document does not get a benign classification just because the parser
    crashed, timed out, or tripped a seccomp rule.
    """

    OK = "ok"  # child exited 0; stdout is trustworthy
    NONZERO_EXIT = "nonzero_exit"  # parser exited with a non-zero status
    KILLED_SIGNAL = "killed_signal"  # SIGSYS (seccomp) / SIGKILL / OOM / etc.
    TIMEOUT = "timeout"  # parent wall-clock kill switch fired
    OUTPUT_OVERFLOW = "output_overflow"  # stdout exceeded the hard cap (bomb guard)
    LAUNCH_FAILED = "launch_failed"  # nsjail could not establish the jail at all


# The set of terminal states that mean "the jail STOPPED the workload".
# A launch failure is deliberately excluded: if we could not even build the
# cage, we have proven nothing and must treat isolation as unestablished.
_CONTAINED_STATUSES = frozenset(
    {
        SandboxStatus.NONZERO_EXIT,
        SandboxStatus.KILLED_SIGNAL,
        SandboxStatus.TIMEOUT,
        SandboxStatus.OUTPUT_OVERFLOW,
    }
)


@dataclass(frozen=True, slots=True)
class SandboxOutcome:
    """The full result of one ``run_sandboxed`` invocation."""

    status: SandboxStatus
    exit_code: int | None  # child exit status (None if signalled / not launched)
    signal: int | None  # terminating signal number (None unless KILLED_SIGNAL)
    stdout: bytes  # captured up to the hard cap
    stderr_tail: str  # last few KB of stderr, for diagnostics only
    duration_s: float  # wall-clock the parent observed
    truncated: bool  # True if stdout hit the cap and the child was killed

    @property
    def launched(self) -> bool:
        """Did the jail actually run the workload (vs. fail to establish)?"""
        return self.status is not SandboxStatus.LAUNCH_FAILED

    @property
    def stopped_by_jail(self) -> bool:
        """Did the jail terminate a workload that started but misbehaved?"""
        return self.status in _CONTAINED_STATUSES


@dataclass(frozen=True, slots=True)
class CanaryProbeResult:
    """Verdict for one hostile canary vector (network/spawn/filesystem/memory)."""

    probe: str
    contained: bool
    detail: str  # human-readable "why" for the audit log


@dataclass(frozen=True, slots=True)
class SandboxVerification:
    """Outcome of the boot-time self-test that re-proves containment.

    ``ok`` is the gate: only when every hostile probe was contained AND the
    benign control extraction succeeded do we arm normal mode. Anything else
    drops the classifier into degraded fail-closed operation.
    """

    ok: bool
    nsjail_path: str | None
    nsjail_version: str | None
    benign_ok: bool  # the control: a legitimate extraction must still succeed
    probes: tuple[CanaryProbeResult, ...] = field(default_factory=tuple)
    failure_reason: str | None = None


class FailReason(enum.Enum):
    """Why an extraction failed closed — persisted as classification provenance."""

    SANDBOX_DEGRADED = "sandbox_degraded"  # cage unproven; not even attempted
    LAUNCH_FAILED = "launch_failed"  # jail could not be established for this doc
    PARSER_CRASH = "parser_crash"  # non-zero exit
    PARSER_KILLED = "parser_killed"  # signalled (seccomp/OOM/...)
    TIMEOUT = "timeout"  # exceeded the time budget
    OUTPUT_OVERFLOW = "output_overflow"  # decompression / output bomb
    BAD_OUTPUT = "bad_output"  # exited 0 but emitted unparseable garbage
    UNSUPPORTED_TYPE = "unsupported_type"  # magic-byte sniff could not route the blob
    EXTRACTOR_UNAVAILABLE = "extractor_unavailable"  # required venv/binary missing on host


@dataclass(frozen=True, slots=True)
class ExtractResult:
    """A successful, trusted extraction. Only produced on a clean jail exit."""

    text: str
    meta: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class FailedClosed:
    """A fail-closed extraction outcome. The caller MUST treat the document as
    the highest sensitivity tier and raise an operator-review flag.

    This is a *reasoned* sentinel — it carries why it failed so the
    classification record stays defensible ("could not prove isolation",
    "parser SIGSYS at ...", etc.).
    """

    reason: FailReason
    detail: str
