"""The sandbox driver: spawn nsjail, enforce the parent kill switch, read
bounded output, and classify how the workload terminated.

This is the only place in EYENET that launches the extraction subprocess. The
parent owns three guarantees the in-jail limits cannot fully provide on their
own:

* **Wall-clock kill switch.** A CPU rlimit cannot catch a ``sleep``; nsjail's
  ``--time_limit`` normally fires first, but the parent has its own deadline as
  a backstop in case nsjail itself wedges.
* **Bounded output.** stdout is read through a hard byte cap so a decompression
  / output bomb cannot exhaust the *parent's* memory. Overflow kills the child.
* **Fail-closed classification.** Any exit that is not a clean ``0`` becomes a
  non-``OK`` :class:`SandboxStatus`; the caller never treats a crash, signal,
  timeout, or overflow as a benign document.
"""

from __future__ import annotations

import contextlib
import os
import selectors
import signal

# Controlled argv, shell=False — the policy is rendered by render_nsjail_argv.
import subprocess  # nosec B404
import time
from typing import TYPE_CHECKING

import structlog

from ._policy import SandboxLimits, render_nsjail_argv
from ._types import SandboxOutcome, SandboxStatus

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

_log = structlog.get_logger()

# nsjail (like a shell) reports a signalled child as 128 + signal number.
_SIGNAL_EXIT_BASE = 128

# Substrings nsjail emits to stderr when it cannot establish the jail at all
# (bad policy, mount failure, unparseable args). These mean "isolation was
# never set up" — distinct from a workload that ran and was then contained.
_LAUNCH_FAIL_MARKERS: tuple[str, ...] = (
    "Couldn't launch the child process",
    "Failed to build mount tree",
    "Couldn't prepare sandboxing policy",
    "Couldn't parse cmdline options",
    "Couldn't mount",
    "Couldn't initialize",
)

_READ_CHUNK = 65536


def classify_returncode(
    returncode: int, stderr_tail: str
) -> tuple[SandboxStatus, int | None, int | None]:
    """Map an nsjail exit code (+ stderr) to a status. Pure; unit-tested.

    Returns ``(status, exit_code, signal)``. nsjail exits ``0`` on a clean child
    exit, ``128 + N`` when the child died on signal ``N`` (e.g. ``159`` = SIGSYS
    from a seccomp denial), the child's own code for a non-zero exit, and emits
    a launch-fail marker when the jail could not be built.
    """
    if any(marker in stderr_tail for marker in _LAUNCH_FAIL_MARKERS):
        return SandboxStatus.LAUNCH_FAILED, None, None
    if returncode == 0:
        return SandboxStatus.OK, 0, None
    if returncode < 0:
        # Popen reports -N when the process it directly spawned died on signal N.
        return SandboxStatus.KILLED_SIGNAL, None, -returncode
    if returncode >= _SIGNAL_EXIT_BASE:
        return SandboxStatus.KILLED_SIGNAL, None, returncode - _SIGNAL_EXIT_BASE
    return SandboxStatus.NONZERO_EXIT, returncode, None


def _kill_group(proc: subprocess.Popen[bytes]) -> None:
    """SIGKILL the child's whole process group, then reap it.

    The child is launched with ``start_new_session=True`` so nsjail and the
    jailed process share a group we can take down in one call.
    """
    with contextlib.suppress(ProcessLookupError):
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    with contextlib.suppress(subprocess.TimeoutExpired):
        proc.wait(timeout=5)
    if proc.returncode is None:
        # Last resort: reap directly so we never leak a zombie.
        with contextlib.suppress(ProcessLookupError, ChildProcessError):
            proc.kill()
            proc.wait(timeout=5)


def _read_ready_fd(
    fd: int, tag: str, out: bytearray, err: bytearray, limits: SandboxLimits
) -> tuple[bool, bool]:
    """Consume one readable fd. Returns ``(eof, overflow)``.

    stdout accumulates up to the cap (overflow signals the caller to kill);
    stderr is kept trimmed to its tail.
    """
    try:
        chunk = os.read(fd, _READ_CHUNK)
    except BlockingIOError:
        return False, False
    if not chunk:
        return True, False
    if tag == "out":
        out += chunk
        return False, len(out) > limits.max_stdout_bytes
    err += chunk
    if len(err) > limits.max_stderr_bytes:
        del err[: len(err) - limits.max_stderr_bytes]
    return False, False


def _drain_bounded(
    proc: subprocess.Popen[bytes], limits: SandboxLimits, deadline: float
) -> tuple[bytes, bytes, bool, bool]:
    """Read stdout/stderr until EOF, deadline, or stdout overflow.

    Returns ``(stdout, stderr_tail_bytes, timed_out, overflowed)``. stdout is
    capped at ``max_stdout_bytes`` (overflow → kill); stderr keeps only the last
    ``max_stderr_bytes`` for diagnostics.
    """
    out = bytearray()
    err = bytearray()
    timed_out = False
    overflowed = False

    sel = selectors.DefaultSelector()
    streams: dict[int, str] = {}
    for stream, tag in ((proc.stdout, "out"), (proc.stderr, "err")):
        if stream is not None:
            fd = stream.fileno()
            os.set_blocking(fd, False)
            sel.register(fd, selectors.EVENT_READ)
            streams[fd] = tag

    try:
        while streams and not overflowed:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            for key, _ in sel.select(timeout=remaining):
                fd = int(key.fd)
                eof, overflowed = _read_ready_fd(fd, streams[fd], out, err, limits)
                if eof:
                    sel.unregister(fd)
                    del streams[fd]
                if overflowed:
                    break
    finally:
        sel.close()

    if len(out) > limits.max_stdout_bytes:
        del out[limits.max_stdout_bytes :]
    return bytes(out), bytes(err[-limits.max_stderr_bytes :]), timed_out, overflowed


def run_sandboxed(
    *,
    nsjail_path: str,
    jail_root: str,
    worker_path: str | None,
    input_path: str | None,
    limits: SandboxLimits,
    worker_args: Sequence[str] = (),
    entrypoint: Sequence[str] | None = None,
    extra_ro_binds: Sequence[tuple[str, str]] = (),
    env: Mapping[str, str] | None = None,
) -> SandboxOutcome:
    """Run one extraction worker inside the jail and report how it terminated.

    Never raises on workload misbehaviour — a crash, signal, timeout, or output
    bomb is returned as a non-``OK`` :class:`SandboxOutcome`. Only genuinely
    unexpected parent-side errors (which the caller treats as fail-closed)
    propagate. The profile knobs (``entrypoint`` / ``extra_ro_binds`` / ``env``)
    default to the Slice-1 stdlib recipe.
    """
    argv = render_nsjail_argv(
        nsjail_path=nsjail_path,
        jail_root=jail_root,
        worker_path=worker_path,
        input_path=input_path,
        limits=limits,
        worker_args=worker_args,
        entrypoint=entrypoint,
        extra_ro_binds=extra_ro_binds,
        env=env,
    )
    started = time.monotonic()
    try:
        # Fully-controlled argv, shell=False; untrusted bytes ride in a bind-mounted file.
        proc = subprocess.Popen(  # noqa: S603  # nosec B603
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    except (FileNotFoundError, PermissionError) as exc:
        _log.error("sandbox.nsjail_unlaunchable", nsjail=nsjail_path, error=str(exc))
        return SandboxOutcome(
            status=SandboxStatus.LAUNCH_FAILED,
            exit_code=None,
            signal=None,
            stdout=b"",
            stderr_tail=str(exc),
            duration_s=time.monotonic() - started,
            truncated=False,
        )

    try:
        deadline = started + limits.parent_timeout_s
        stdout, stderr_bytes, timed_out, overflowed = _drain_bounded(proc, limits, deadline)

        if timed_out or overflowed:
            _kill_group(proc)
            returncode = proc.returncode if proc.returncode is not None else -signal.SIGKILL
        else:
            try:
                returncode = proc.wait(timeout=max(0.0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                timed_out = True
                _kill_group(proc)
                returncode = proc.returncode if proc.returncode is not None else -signal.SIGKILL

        stderr_tail = stderr_bytes.decode("utf-8", "replace")

        if timed_out:
            status, exit_code, sig = SandboxStatus.TIMEOUT, None, None
        elif overflowed:
            status, exit_code, sig = SandboxStatus.OUTPUT_OVERFLOW, None, None
        else:
            status, exit_code, sig = classify_returncode(returncode, stderr_tail)

        duration = time.monotonic() - started
        if status is not SandboxStatus.OK:
            _log.warning(
                "sandbox.run_non_ok",
                status=status.value,
                exit_code=exit_code,
                signal=sig,
                duration_s=round(duration, 3),
                truncated=overflowed,
            )
        return SandboxOutcome(
            status=status,
            exit_code=exit_code,
            signal=sig,
            stdout=stdout,
            stderr_tail=stderr_tail,
            duration_s=duration,
            truncated=overflowed,
        )
    finally:
        # Close the PIPE streams we own so we never leak fds per extraction.
        for stream in (proc.stdout, proc.stderr):
            if stream is not None:
                with contextlib.suppress(OSError):
                    stream.close()
