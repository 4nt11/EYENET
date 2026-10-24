# SPDX-License-Identifier: AGPL-3.0-or-later
"""Locate + invoke the ulpextract Go binary (prod-grade, shipped wheels-in).

The extractor is a batch CLI: file paths in, ``host\\turl\\tlogin\\tpassword\\tscheme\\t
tld\\tsource\\tip_class`` TSV out. We invoke it as a SUBPROCESS (never gopy/cgo):
process isolation keeps a panic/OOM on an attacker-controlled archive out of the
service's address space, and its NumCPU worker pool + streamed stdout pipe straight
into the ClickHouse insert.

Binary resolution order: ``EYENET_ULPEXTRACT_BIN`` env override → the binary built next
to the in-package Go source (``eyenet/stealer/ulpextract/ulpextract``, produced by the
Dockerfile.stealer builder) → ``ulpextract`` on PATH.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

_PKG_BIN = Path(__file__).parent / "ulpextract" / "ulpextract"


def ulpextract_path() -> str:
    """Absolute path to the ulpextract binary. Raises if it cannot be found."""
    override = os.environ.get("EYENET_ULPEXTRACT_BIN")
    if override:
        if not Path(override).is_file():
            raise FileNotFoundError(f"EYENET_ULPEXTRACT_BIN points at a missing file: {override}")
        return override
    if _PKG_BIN.is_file():
        return str(_PKG_BIN)
    on_path = shutil.which("ulpextract")
    if on_path:
        return on_path
    raise FileNotFoundError(
        "ulpextract binary not found — build it from eyenet/stealer/ulpextract "
        "(go build -o ulpextract ./ulpextract.go), set EYENET_ULPEXTRACT_BIN, or "
        "put it on PATH"
    )


__all__ = ["ulpextract_path"]
