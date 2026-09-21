"""Self-reported host stats body for `GET /v1/system` (authenticated).

Orthanc-style operator canary: CPU / RAM / disk / load + version. Gated behind
`read:metrics` — host stats never go on an unauthenticated surface. API_PLAN §3.6.
"""

from __future__ import annotations

from ._base import ApiSchema


class MemStats(ApiSchema):
    used: int
    total: int
    percent: float


class DiskUsage(ApiSchema):
    used: int
    free: int
    total: int


class DiskStats(ApiSchema):
    data: DiskUsage
    root: DiskUsage


class SystemStats(ApiSchema):
    """Point-in-time host self-report."""

    cpu_percent: float
    mem: MemStats
    disk: DiskStats
    load1: float
    version: str


__all__ = ["DiskStats", "DiskUsage", "MemStats", "SystemStats"]
