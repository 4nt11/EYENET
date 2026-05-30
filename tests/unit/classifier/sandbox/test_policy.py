"""The pinned eyenet-extract policy: argv rendering + limit invariants."""

from __future__ import annotations

import pytest

from eyenet.classifier.sandbox._policy import (
    INPUT_DEST,
    RUNTIME_BINDS,
    SANDBOX_GID,
    SANDBOX_UID,
    WORKER_DEST,
    SandboxLimits,
    render_nsjail_argv,
)

pytestmark = pytest.mark.unit


def test_argv_carries_the_locked_recipe() -> None:
    argv = render_nsjail_argv(
        nsjail_path="/usr/local/bin/nsjail",
        jail_root="jailroot",
        worker_path="worker.py",
        input_path="input.bin",
        limits=SandboxLimits(),
        worker_args=("network",),
    )
    assert argv[0] == "/usr/local/bin/nsjail"
    # User-namespace mapping to the nobody-equivalent id.
    assert "--user" in argv and str(SANDBOX_UID) in argv
    assert "--group" in argv and str(SANDBOX_GID) in argv
    # Ephemeral RW root + RO runtime binds.
    assert "--rw" in argv
    for src in RUNTIME_BINDS:
        assert src in argv
    # seccomp allowlist present.
    assert "--seccomp_string" in argv
    pol = argv[argv.index("--seccomp_string") + 1]
    assert "DEFAULT KILL" in pol
    # Dangerous syscalls are NOT in the allowlist.
    for banned in ("clone", "fork", "vfork", "ptrace"):
        assert f" {banned}," not in pol and f" {banned}\n" not in pol
    # Worker + input mounted at the fixed in-jail destinations; arg passed last.
    assert f"worker.py:{WORKER_DEST}" in argv
    assert f"input.bin:{INPUT_DEST}" in argv
    assert argv[-1] == "network"
    assert WORKER_DEST in argv


def test_argv_without_input_omits_input_bind() -> None:
    argv = render_nsjail_argv(
        nsjail_path="/n",
        jail_root="/r",
        worker_path="/w.py",
        input_path=None,
        limits=SandboxLimits(),
    )
    assert not any(part.endswith(f":{INPUT_DEST}") for part in argv)


def test_limits_reject_parent_timeout_not_exceeding_jail_limit() -> None:
    with pytest.raises(ValueError, match="parent_timeout_s must exceed"):
        SandboxLimits(time_limit_s=30, parent_timeout_s=30)


def test_limits_reject_nonpositive() -> None:
    with pytest.raises(ValueError, match="positive"):
        SandboxLimits(rlimit_as_mb=0)
