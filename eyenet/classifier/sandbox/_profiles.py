"""Profile builders — resolve host resources into least-privilege recipes.

A :class:`SandboxProfile` is a pure value (allowlist + binds + env + entrypoint).
*Building* a concrete one means probing the host: locating the dedicated
``eyenet-extract`` venv, its ``site-packages``, the Tesseract binary, and its
language data. That host-probing is the sandbox boundary's responsibility — the
extraction adapters above only ask for ``venv_profile()`` / ``tesseract_profile()``
and get back a ready recipe or ``None`` (resource absent → the caller fails that
document closed; it is never a global degrade).

Nothing here parses untrusted bytes; it only inspects the operator's own install.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from ._policy import (
    DEFAULT_EXTRACT_VENV,
    EXTRACT_VENV_ENV,
    INPUT_DEST,
    SINGLE_THREAD_ENV,
    STDLIB_PROFILE,
    TESSDATA_DEST,
    VENV_SITE_DEST,
    SandboxProfile,
)

# Common locations for Tesseract's language data, tried in order when the
# TESSDATA_PREFIX env var is unset. All normally live under /usr (already bound).
_TESSDATA_CANDIDATES: tuple[str, ...] = (
    "/usr/share/tesseract/tessdata",
    "/usr/share/tessdata",
    "/usr/share/tesseract-ocr/5/tessdata",
    "/usr/share/tesseract-ocr/4.00/tessdata",
    "/usr/local/share/tessdata",
)


def resolve_extract_venv() -> Path | None:
    """The dedicated parser venv, or None if it is not installed.

    Honours the ``EYENET_EXTRACT_VENV`` override, else the packaged default.
    """
    candidate = Path(os.environ.get(EXTRACT_VENV_ENV, DEFAULT_EXTRACT_VENV))
    return candidate if candidate.is_dir() else None


def venv_site_packages(venv: Path) -> Path | None:
    """Locate ``<venv>/lib/python3.*/site-packages``, or None if absent."""
    matches = sorted(venv.glob("lib/python3.*/site-packages"))
    return matches[0] if matches else None


def discover_tesseract() -> tuple[str | None, str | None]:
    """Locate the ``tesseract`` binary + its tessdata dir. Never raises."""
    binary = shutil.which("tesseract")
    if binary is None:
        return None, None
    env_prefix = os.environ.get("TESSDATA_PREFIX")
    if env_prefix and Path(env_prefix).is_dir():
        return binary, env_prefix
    for candidate in _TESSDATA_CANDIDATES:
        if Path(candidate).is_dir():
            return binary, candidate
    return binary, None


def stdlib_profile() -> SandboxProfile:
    """The base recipe: stdlib-only Python worker, base allowlist, no extra binds."""
    return STDLIB_PROFILE


def venv_profile() -> SandboxProfile | None:
    """Recipe for a Python worker that imports the dedicated venv's libraries.

    Binds the venv ``site-packages`` read-only at ``/site`` and puts it on
    ``PYTHONPATH``, with the single-thread env so C-extension libraries
    (pymupdf, numpy/BLAS) never attempt thread creation under the no-clone3
    allowlist. Returns None if the venv is not installed.
    """
    venv = resolve_extract_venv()
    if venv is None:
        return None
    site = venv_site_packages(venv)
    if site is None:
        return None
    return SandboxProfile(
        name="venv",
        extra_ro_binds=((str(site), VENV_SITE_DEST),),
        env=(("PYTHONPATH", VENV_SITE_DEST), *SINGLE_THREAD_ENV),
    )


def tesseract_profile(*, langs: str = "eng") -> SandboxProfile | None:
    """Recipe running Tesseract as its OWN jail entrypoint (no Python worker).

    Tesseract reads the bound ``/input`` and writes the OCR text to stdout
    (``interpret="raw_text"`` on the chokepoint). The single-thread env keeps its
    OpenMP runtime from spawning worker threads (which would hit the no-clone3
    allowlist), so it runs within the base allowlist. Returns None if the binary
    is not installed.
    """
    binary, tessdata = discover_tesseract()
    if binary is None:
        return None
    extra: tuple[tuple[str, str], ...] = ()
    env: tuple[tuple[str, str], ...] = SINGLE_THREAD_ENV
    if tessdata is not None:
        extra = ((tessdata, TESSDATA_DEST),)
        env = (("TESSDATA_PREFIX", TESSDATA_DEST), *SINGLE_THREAD_ENV)
    return SandboxProfile(
        name="tesseract",
        extra_ro_binds=extra,
        env=env,
        entrypoint=(binary, INPUT_DEST, "stdout", "-l", langs),
    )
