"""The pinned eyenet-extract policy: argv rendering + limit invariants."""

from __future__ import annotations

import pytest

from eyenet.classifier.sandbox._policy import (
    INPUT_DEST,
    RUNTIME_BINDS,
    SANDBOX_GID,
    SANDBOX_UID,
    SECCOMP_ALLOWLIST,
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


def test_one_allowlist_never_permits_process_or_thread_creation() -> None:
    # The single base allowlist must never permit spawning or thread creation —
    # clone3 (modern thread/spawn) and the classic clone/fork/vfork all stay out,
    # so parsers run single-threaded with no in-jail process spawn. This is the
    # property the boot canary proves at runtime.
    for banned in ("clone", "clone3", "fork", "vfork", "ptrace", "mount", "bpf"):
        assert f" {banned}," not in SECCOMP_ALLOWLIST
        assert f" {banned}\n" not in SECCOMP_ALLOWLIST


def test_argv_entrypoint_overrides_python_worker() -> None:
    argv = render_nsjail_argv(
        nsjail_path="/n",
        jail_root="/r",
        worker_path=None,  # Tesseract has no Python worker
        input_path="in.bin",
        limits=SandboxLimits(),
        entrypoint=("/usr/bin/tesseract", INPUT_DEST, "stdout", "-l", "eng"),
    )
    # The entrypoint is the tail; no Python worker is mounted.
    tail = argv[argv.index("--") + 1 :]
    assert tail == ["/usr/bin/tesseract", INPUT_DEST, "stdout", "-l", "eng"]
    assert not any(WORKER_DEST in part for part in argv)
    assert f"in.bin:{INPUT_DEST}" in argv


def test_argv_renders_extra_binds_and_env() -> None:
    argv = render_nsjail_argv(
        nsjail_path="/n",
        jail_root="/r",
        worker_path="/w.py",
        input_path=None,
        limits=SandboxLimits(),
        extra_ro_binds=(("/opt/venv/site", "/site"),),
        env={"PYTHONPATH": "/site"},
    )
    assert "/opt/venv/site:/site" in argv
    assert "--env" in argv and "PYTHONPATH=/site" in argv
