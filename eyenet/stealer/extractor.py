# SPDX-License-Identifier: AGPL-3.0-or-later
"""Locate + invoke the gotractor Go binary (prod-grade, shipped wheels-in).

gotractor is a long-lived daemon speaking newline-delimited JSON on
stdin/stdout. The Python side writes `{"cmd":"run","input":...}` commands
and reads back one record per matched rule plus a terminating run_done
frame. We invoke it as a SUBPROCESS (never gopy/cgo): process isolation
keeps a panic/OOM on an attacker-controlled archive out of the service's
address space.

Binary resolution order: `EYENET_GOTRACTOR_BIN` env override, then the
binary built next to the in-package Go source
(`eyenet/stealer/gotractor/gotractor`, produced by the Dockerfile.stealer
builder), then `gotractor` on PATH.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

_GOTRACTOR_PKG_BIN = Path(__file__).parent / "gotractor" / "gotractor"


def gotractor_path() -> str:
    """Absolute path to the gotractor binary. Raises if it cannot be found."""
    override = os.environ.get("EYENET_GOTRACTOR_BIN")
    if override:
        if not Path(override).is_file():
            raise FileNotFoundError(f"EYENET_GOTRACTOR_BIN points at a missing file: {override}")
        return override
    if _GOTRACTOR_PKG_BIN.is_file():
        return str(_GOTRACTOR_PKG_BIN)
    on_path = shutil.which("gotractor")
    if on_path:
        return on_path
    raise FileNotFoundError(
        "gotractor binary not found: build it from eyenet/stealer/gotractor "
        "(go build -o gotractor .), set EYENET_GOTRACTOR_BIN, or "
        "put it on PATH"
    )


__all__ = ["gotractor_path"]
