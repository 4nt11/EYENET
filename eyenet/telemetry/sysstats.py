"""Self-reported host stats — the single source for the /v1/system endpoint
and the ``eyenet_sys_*`` OTel gauges (CPU / RAM / disk / load).

Linux-oriented (small-operator scope); ``os.getloadavg`` is guarded so a
non-Linux host degrades to 0.0 rather than crashing the probe.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

import psutil


def disk(path: Path) -> dict[str, int]:
    """Bytes used/free/total for the volume backing ``path``."""
    usage = shutil.disk_usage(path)
    return {"used": usage.used, "free": usage.free, "total": usage.total}


def load1() -> float:
    """1-minute load average (0.0 where the platform has no getloadavg)."""
    return os.getloadavg()[0] if hasattr(os, "getloadavg") else 0.0


def snapshot(data_dir: Path) -> dict[str, Any]:
    """Point-in-time host stats keyed to match the ``SystemStats`` schema."""
    vm = psutil.virtual_memory()
    return {
        # ponytail: interval=None is non-blocking; the first read after process
        # start is 0.0 and self-corrects on the next call. Upgrade path = a
        # background sampler only if a true instantaneous % ever matters.
        "cpu_percent": psutil.cpu_percent(interval=None),
        "mem": {"used": vm.used, "total": vm.total, "percent": vm.percent},
        "disk": {"data": disk(data_dir), "root": disk(Path("/"))},
        "load1": load1(),
    }


__all__ = ["disk", "load1", "snapshot"]
