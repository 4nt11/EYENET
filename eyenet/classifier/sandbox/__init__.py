"""Extraction sandbox — the security boundary for parsing hostile documents.

Public surface:

* :func:`arm_sandbox` — run the boot canary; arm normal mode or degrade.
* :func:`extract_sandboxed` — the one chokepoint: blob -> text, or fail closed.
* :func:`verify_sandbox` — re-prove containment on demand.
* :func:`sandbox_state` / :func:`current_verification` — observe the gate.
* :class:`ExtractResult` / :class:`FailedClosed` — the extraction outcome union.

Internal modules are underscore-prefixed; import only from this package.
"""

from __future__ import annotations

from ._canary import CANARY_PROBES, discover_nsjail, verify_sandbox
from ._chokepoint import (
    SandboxState,
    arm_sandbox,
    current_verification,
    extract_sandboxed,
    reset_sandbox,
    sandbox_state,
)
from ._policy import DEFAULT_LIMITS, SandboxLimits, SandboxProfile
from ._profiles import (
    discover_tesseract,
    resolve_extract_venv,
    stdlib_profile,
    tesseract_profile,
    venv_profile,
)
from ._types import (
    CanaryProbeResult,
    ExtractResult,
    FailedClosed,
    FailReason,
    SandboxOutcome,
    SandboxStatus,
    SandboxVerification,
)

__all__ = [
    "CANARY_PROBES",
    "DEFAULT_LIMITS",
    "CanaryProbeResult",
    "ExtractResult",
    "FailReason",
    "FailedClosed",
    "SandboxLimits",
    "SandboxOutcome",
    "SandboxProfile",
    "SandboxState",
    "SandboxStatus",
    "SandboxVerification",
    "arm_sandbox",
    "current_verification",
    "discover_nsjail",
    "discover_tesseract",
    "extract_sandboxed",
    "reset_sandbox",
    "resolve_extract_venv",
    "sandbox_state",
    "stdlib_profile",
    "tesseract_profile",
    "venv_profile",
    "verify_sandbox",
]
