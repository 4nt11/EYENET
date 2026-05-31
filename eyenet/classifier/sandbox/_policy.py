"""The pinned ``eyenet-extract`` nsjail policy — versioned as code.

This module IS the policy artifact. It encodes the exact, empirically-derived
recipe that the boot canary re-proves on every startup:

* **userns → uid/gid 99999** (an account that owns nothing), ``NoNewPrivs``,
  all capabilities dropped (nsjail defaults under ``CLONE_NEWUSER``).
* **No network namespace interface** — ``CLONE_NEWNET`` is on by default, so the
  jail has no route; the canary proves ``connect()`` to a public IP fails.
* **Ephemeral RW tmpfs root** with only RO bind mounts of ``/usr`` + ``/lib64``
  (the interpreter + stdlib) and the per-parse RO input. The kernel under an
  unprivileged userns refuses to remount the pivot root read-only, so the root
  is a throwaway tmpfs (empty, nobody-owned, size/fsize-capped, discarded per
  run); every byte of *real* content is mounted read-only.
* **RLIMIT_AS / RLIMIT_CPU / RLIMIT_FSIZE** + nsjail ``--time_limit`` bound
  memory, CPU, file size, and wall-clock.
* **seccomp-bpf allowlist, default KILL.** Derived from the observed CPython
  startup syscall set (captured via in-jail strace), plus safe compute
  headroom. ``clone`` / ``fork`` / ``vfork`` / ``ptrace`` / ``mount`` / ``bpf``
  and friends are deliberately ABSENT — a workload that needs a new syscall
  fails *closed* (SIGSYS), never open. The network syscalls are allowed (glibc
  NSS probes the absent nscd socket at startup); network *containment* is the
  empty net namespace's job, not seccomp's.

One allowlist covers every parser. Empirically (strace under a real jail),
pymupdf, python-docx, and Tesseract all run within this set **single-threaded** —
their only would-be extra was thread creation, which on modern glibc routes
through ``clone3``. ``clone3`` passes its flags behind a struct pointer, so
seccomp cannot tell a thread (``CLONE_THREAD``) from a process spawn; allowing it
would reopen process spawning. We therefore keep it KILLed and force parsers
single-threaded via ``SINGLE_THREAD_ENV`` instead — preserving the no-spawn
guarantee the canary proves. A parser that ignores the hint and tries ``clone3``
fails *closed* (SIGSYS), never open.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

# uid/gid the jailed process is mapped to inside the user namespace. A high,
# unallocated id that owns no files on any sane host (effectively "nobody").
SANDBOX_UID = 99999
SANDBOX_GID = 99999

# The interpreter that runs extraction workers INSIDE the jail. It must live
# under one of RUNTIME_BINDS. We use the system interpreter (not sys.executable,
# which is usually a venv path outside /usr and therefore absent in the jail).
# Stdlib-only workers run here; the venv-backed workers add the venv
# site-packages bind + PYTHONPATH (see _profiles), still on this interpreter.
SANDBOX_INTERPRETER = "/usr/bin/python3"

# Read-only runtime mounts: the interpreter, shared libraries, and the ELF
# loader (/lib64/ld-linux-*). On usrmerge systems /lib64 is a symlink into /usr,
# but the empty jail root needs the path to exist, so we bind it explicitly.
RUNTIME_BINDS: tuple[str, ...] = ("/usr", "/lib64")

# In-jail paths the worker and its single input are mounted at.
WORKER_DEST = "/worker.py"
INPUT_DEST = "/input"

# The kafel seccomp-bpf policy. DEFAULT KILL: any syscall not listed terminates
# the process with SIGSYS. SYSCALL[5] is fstat (x86_64), which this kafel build
# lacks by name. clone/fork/vfork/ptrace/mount/bpf are intentionally omitted.
#
# Slice-4 additions (strace-derived from presidio-analyzer + spaCy es/en NER,
# single-threaded under SINGLE_THREAD_ENV). Each is in a class the existing
# confinement already contains — none reopens process spawning, host-FS tamper,
# or the network route:
#   mbind            NUMA memory policy (numpy/blis at import) — self-memory only
#   mkdir/rename/    cache file management (thinc/tldextract) — confined to the
#     unlink/flock     ephemeral RW tmpfs root (RO binds stay immutable,
#                      RLIMIT_FSIZE bounds writes, all discarded per run)
#   bind/getpeername socket calls — contained by the empty net namespace (no
#                      route), exactly as the already-allowed socket/connect/sendto
# clone3 stays KILLed: a thread that escapes SINGLE_THREAD_ENV still fails closed.
SECCOMP_ALLOWLIST = """\
POLICY eyenet_extract {
  ALLOW {
    SYSCALL[5],
    access, arch_prctl, brk, close, connect, epoll_create1, epoll_ctl,
    epoll_pwait2, epoll_wait, execve, fcntl, futex, getdents64, getdents,
    getegid, geteuid, getgid, getpid, getrandom, gettid, getuid, getcwd,
    ioctl, lseek, mmap, mremap, mprotect, munmap, newfstatat, statx,
    open, openat, prctl, pread64, prlimit64, read, readv, readlink,
    recvfrom, recvmsg, rseq, rt_sigaction, rt_sigprocmask, rt_sigreturn,
    sched_getaffinity, sched_yield, sendto, sendmsg, set_robust_list,
    set_tid_address, socket, getsockname, getsockopt, setsockopt, shutdown,
    timerfd_create, timerfd_settime, write, writev, exit, exit_group,
    clock_gettime, clock_getres, clock_nanosleep, nanosleep, poll, ppoll,
    pselect6, pipe2, dup, dup2, dup3, newuname, sysinfo, sigaltstack,
    madvise, eventfd2, fstatfs, statfs, membarrier, restart_syscall,
    mbind, flock, mkdir, rename, unlink, bind, getpeername
  }
}
USE eyenet_extract DEFAULT KILL
"""

# Environment that forces parser libraries to stay single-threaded. With these
# set, pymupdf / Tesseract / numpy-BLAS never attempt clone3 thread creation, so
# they run within the (process-spawn-free) base allowlist. A library that ignores
# the hint and tries to spawn a thread anyway hits DEFAULT KILL → fail closed.
SINGLE_THREAD_ENV: tuple[tuple[str, str], ...] = (
    ("OMP_THREAD_LIMIT", "1"),
    ("OMP_NUM_THREADS", "1"),
    ("OPENBLAS_NUM_THREADS", "1"),
    ("MKL_NUM_THREADS", "1"),
)

# The dedicated parser venv (built by setup; see README §"Document Classifier").
# A box that never extracts may lack it — missing => the affected formats fail
# closed at dispatch, not a global degrade. The env override lets an operator
# relocate it; the in-jail mount points are fixed so workers reference one path.
DEFAULT_EXTRACT_VENV = "/opt/eyenet/extract-venv"
EXTRACT_VENV_ENV = "EYENET_EXTRACT_VENV"
VENV_SITE_DEST = "/site"  # where the venv's site-packages is bound (RO) in-jail
TESSDATA_DEST = "/tessdata"  # where Tesseract language data is bound (RO) in-jail


@dataclass(frozen=True, slots=True)
class SandboxProfile:
    """A least-privilege execution recipe for one class of extraction worker.

    The default profile is the stdlib-only Python worker with no extra binds —
    i.e. exactly the Slice-1 behaviour. Parser classes that need more (the venv on
    ``PYTHONPATH``, Tesseract's own entrypoint, single-thread env) carry only the
    additional binds/env they require. All profiles share the one base seccomp
    allowlist — privilege is added through binds and env, never new syscalls.
    """

    name: str
    extra_ro_binds: tuple[tuple[str, str], ...] = ()  # (host_src, jail_dest) pairs
    env: tuple[tuple[str, str], ...] = ()  # (key, value) — rendered as --env K=V
    entrypoint: tuple[str, ...] | None = None  # None => [interpreter, /worker.py, *args]


# The Slice-1 default: stdlib Python worker, base allowlist, no extra binds.
STDLIB_PROFILE = SandboxProfile(name="stdlib")


@dataclass(frozen=True, slots=True)
class SandboxLimits:
    """Resource + time budget for a single sandboxed extraction.

    ``parent_timeout_s`` must exceed ``time_limit_s`` so nsjail's own wall-clock
    kill normally fires first; the parent timeout is the backstop for nsjail
    itself hanging.
    """

    rlimit_as_mb: int = 1024  # address space ceiling (the memory guarantee)
    rlimit_cpu_s: int = 10  # CPU seconds
    rlimit_fsize_mb: int = 16  # max single file the worker may write (to tmpfs)
    time_limit_s: int = 30  # nsjail wall-clock cap on the jail
    parent_timeout_s: int = 40  # parent kill-switch deadline (> time_limit_s)
    max_stdout_bytes: int = 8 * 1024 * 1024  # output-bomb guard
    max_stderr_bytes: int = 4 * 1024  # diagnostic tail only

    def __post_init__(self) -> None:
        if self.parent_timeout_s <= self.time_limit_s:
            raise ValueError(
                "parent_timeout_s must exceed time_limit_s so nsjail's own "
                "kill fires before the parent backstop"
            )
        if self.max_stdout_bytes <= 0 or self.rlimit_as_mb <= 0:
            raise ValueError("limits must be positive")


DEFAULT_LIMITS = SandboxLimits()


def render_nsjail_argv(
    *,
    nsjail_path: str,
    jail_root: str,
    worker_path: str | None,
    input_path: str | None,
    limits: SandboxLimits,
    worker_args: Sequence[str] = (),
    interpreter: str = SANDBOX_INTERPRETER,
    entrypoint: Sequence[str] | None = None,
    extra_ro_binds: Sequence[tuple[str, str]] = (),
    env: Mapping[str, str] | None = None,
) -> list[str]:
    """Build the full, shell-free nsjail argv for one extraction run.

    Every element is controlled by EYENET — the untrusted bytes travel in the
    bind-mounted ``input_path`` file, never on the command line. ``jail_root``
    is a caller-owned empty directory used as the throwaway tmpfs root.

    The defaults reproduce the Slice-1 recipe exactly (stdlib Python worker,
    ``/usr`` + ``/lib64`` only). The optional knobs carry the per-parser privilege
    a profile needs: ``extra_ro_binds`` for the venv site-packages or Tesseract
    data, ``env`` for ``PYTHONPATH`` / ``TESSDATA_PREFIX`` / single-thread limits,
    and ``entrypoint`` for a non-Python command (Tesseract runs as its own jail
    entrypoint — we cannot shell out to it from Python because process spawning is
    killed). All runs share the one base seccomp allowlist.
    """
    argv: list[str] = [
        nsjail_path,
        "--quiet",
        "--mode",
        "o",  # MODE_STANDALONE_ONCE
        "--rw",  # ephemeral tmpfs root is writable (empty, discarded); binds stay RO
        "--user",
        str(SANDBOX_UID),
        "--group",
        str(SANDBOX_GID),
        "--chroot",
        jail_root,
        "--rlimit_as",
        str(limits.rlimit_as_mb),
        "--rlimit_cpu",
        str(limits.rlimit_cpu_s),
        "--rlimit_fsize",
        str(limits.rlimit_fsize_mb),
        "--time_limit",
        str(limits.time_limit_s),
        "--seccomp_string",
        SECCOMP_ALLOWLIST,
    ]
    for key, value in (env or {}).items():
        argv += ["--env", f"{key}={value}"]
    for src in RUNTIME_BINDS:
        argv += ["--bindmount_ro", src]
    for src, dest in extra_ro_binds:
        argv += ["--bindmount_ro", f"{src}:{dest}"]
    if worker_path is not None:
        argv += ["--bindmount_ro", f"{worker_path}:{WORKER_DEST}"]
    if input_path is not None:
        argv += ["--bindmount_ro", f"{input_path}:{INPUT_DEST}"]
    if entrypoint is not None:
        argv += ["--", *entrypoint]
    else:
        argv += ["--", interpreter, WORKER_DEST, *worker_args]
    return argv
