# SPDX-License-Identifier: AGPL-3.0-or-later
"""Timezone inference from circadian signals (the SMART-CONSUMER side).

BEHAVE-TEXT emits UTC-anchored activity distributions; EYENET turns them into an
operator-facing offset and, when a second signal agrees, a single IANA zone. This
module is pure (no IO, no storage) so it can run read-time on an actor-detail
request and be exhaustively unit-tested.

Honesty contract (this is forensic evidence, never bare fact):
* timing alone yields an OFFSET and a candidate ZONE LIST, never one asserted zone;
* a single zone_best is only emitted when a second signal (dialect region's
  country) agrees with the circadian offset;
* confidence is capped for thin actors and for histograms with no gated sleep gap;
* a tz is always a HINT with its supporting_signals shown — it breaks for shift
  workers, teams, scheduled bots and personas merged across real timezones.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

# Local sleep-center assumption: the midpoint of the quiet span sits ~03:30 local.
_SLEEP_CENTER_LOCAL = 3.5
_QUIET_WIDTH_FALLBACK = 7  # hours; proxy sleep window when no gated quiet_span exists
_THIN_ACTOR_MESSAGES = 30  # below this, cap confidence at "low"
_MAX_OFFSET = 14  # real-world UTC offset bounds (Kiribati +14 .. Baker Island -12)
_MIN_OFFSET = -12

# Country (ISO-3166 alpha-2) -> representative IANA zones, most-populous first.
# Curated for the CTI-relevant + major Spanish/Portuguese/Russian/English markets;
# single-zone countries need one entry, multi-zone ones list the mainland zones the
# circadian offset then disambiguates. Extend as new dialect regions surface.
_COUNTRY_ZONES: dict[str, list[str]] = {
    "CL": ["America/Santiago"],
    "AR": ["America/Argentina/Buenos_Aires"],
    "UY": ["America/Montevideo"],
    "PY": ["America/Asuncion"],
    "BO": ["America/La_Paz"],
    "PE": ["America/Lima"],
    "EC": ["America/Guayaquil"],
    "CO": ["America/Bogota"],
    "VE": ["America/Caracas"],
    "BR": ["America/Sao_Paulo", "America/Manaus", "America/Noronha"],
    "MX": ["America/Mexico_City", "America/Tijuana", "America/Cancun"],
    "ES": ["Europe/Madrid", "Atlantic/Canary"],
    "US": ["America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles"],
    "CA": ["America/Toronto", "America/Winnipeg", "America/Edmonton", "America/Vancouver"],
    "GB": ["Europe/London"],
    "PT": ["Europe/Lisbon"],
    "FR": ["Europe/Paris"],
    "DE": ["Europe/Berlin"],
    "IT": ["Europe/Rome"],
    "NL": ["Europe/Amsterdam"],
    "RU": ["Europe/Moscow", "Asia/Yekaterinburg", "Asia/Novosibirsk", "Asia/Vladivostok"],
    "UA": ["Europe/Kyiv"],
    "TR": ["Europe/Istanbul"],
    "IN": ["Asia/Kolkata"],
    "CN": ["Asia/Shanghai"],
    "ID": ["Asia/Jakarta"],
    "PH": ["Asia/Manila"],
    "NG": ["Africa/Lagos"],
    "ZA": ["Africa/Johannesburg"],
    "AU": ["Australia/Sydney", "Australia/Perth"],
}

# Representative zones per integer UTC offset, for the no-dialect display case.
_OFFSET_SAMPLE_ZONES: dict[int, list[str]] = {
    -8: ["America/Los_Angeles"],
    -7: ["America/Denver"],
    -6: ["America/Chicago", "America/Mexico_City"],
    -5: ["America/New_York", "America/Bogota", "America/Lima"],
    -4: ["America/Santiago", "America/Caracas", "America/Halifax"],
    -3: ["America/Sao_Paulo", "America/Argentina/Buenos_Aires", "America/Montevideo"],
    0: ["Europe/London", "Africa/Abidjan"],
    1: ["Europe/Madrid", "Europe/Paris", "Africa/Lagos"],
    2: ["Europe/Kyiv", "Africa/Johannesburg", "Europe/Istanbul"],
    3: ["Europe/Moscow", "Asia/Baghdad"],
    4: ["Asia/Dubai"],
    5: ["Asia/Karachi", "Asia/Yekaterinburg"],
    6: ["Asia/Dhaka"],
    7: ["Asia/Jakarta", "Asia/Bangkok"],
    8: ["Asia/Shanghai", "Asia/Singapore"],
    9: ["Asia/Tokyo", "Asia/Seoul"],
    10: ["Australia/Sydney"],
}


@dataclass
class InferredTz:
    offset_hours: int | None
    zone_best: str | None
    zone_candidates: list[str]
    confidence: str  # "none" | "low" | "medium" | "high"
    supporting_signals: list[str] = field(default_factory=list)
    local_active_window: tuple[int, int] | None = None  # [start, end) local hours
    quiet_window_utc: tuple[int, int] | None = None


def _fold_offset(off: float) -> int:
    """Round to the nearest hour and fold into the real-world [-12, +14] range."""
    o = round(off)
    while o > _MAX_OFFSET:
        o -= 24
    while o < _MIN_OFFSET:
        o += 24
    return o


def _span_midpoint(start: int, end: int) -> float:
    """Midpoint of a circular [start, end) hour span (end may be < start = wrap)."""
    length = (end - start) % 24 or 24
    return (start + length / 2) % 24


def _min_density_window(hour_histogram: list[float], width: int) -> tuple[int, int]:
    """Circular window of `width` hours with the least total activity -> [start, end)."""
    best_start, best_sum = 0, None
    for start in range(24):
        total = sum(hour_histogram[(start + k) % 24] for k in range(width))
        if best_sum is None or total < best_sum:
            best_start, best_sum = start, total
    return (best_start, (best_start + width) % 24)


def _offset_from_quiet_midpoint(midpoint_utc: float) -> int:
    return _fold_offset(_SLEEP_CENTER_LOCAL - midpoint_utc)


def _zone_offset_hours(zone: str, at: datetime) -> int | None:
    try:
        off = ZoneInfo(zone).utcoffset(at)
    except Exception:
        return None
    if off is None:
        return None
    return round(off.total_seconds() / 3600)


def _shift_window(window_utc: tuple[int, int], offset: int) -> tuple[int, int]:
    s, e = window_utc
    return ((s + offset) % 24, (e + offset) % 24)


def _active_window_utc(quiet_utc: tuple[int, int]) -> tuple[int, int]:
    """The complement of the quiet span is the active span."""
    qs, qe = quiet_utc
    return (qe % 24, qs % 24)


def infer_timezone(
    *,
    hour_histogram: list[float] | None,
    quiet_span_utc: tuple[int, int] | None,
    total_messages: int,
    dialect_region: str | None = None,
    at: datetime | None = None,
) -> InferredTz:
    """Infer an operator-facing timezone from circadian + (optional) dialect signals."""
    at = at or datetime.now(UTC)
    signals: list[str] = []

    if not hour_histogram or sum(hour_histogram) == 0:
        return InferredTz(None, None, [], "none")

    # 1) Quiet (sleep) window: the gated primitive if present, else a proxy from the
    #    histogram's least-active contiguous window (lower confidence).
    gated = quiet_span_utc is not None
    quiet_utc = quiet_span_utc or _min_density_window(hour_histogram, _QUIET_WIDTH_FALLBACK)
    if gated:
        signals.append("circadian.quiet_span")
    else:
        signals.append("circadian.hour_histogram")

    offset = _offset_from_quiet_midpoint(_span_midpoint(*quiet_utc))

    # 2) Dialect fusion: the region's country picks the exact zone at that offset.
    zone_best: str | None = None
    country_zones: list[str] = []
    if dialect_region and "-" in dialect_region:
        country = dialect_region.split("-", 1)[1].upper()
        country_zones = _COUNTRY_ZONES.get(country, [])
        if country_zones:
            signals.append(f"lexical.dialect_region={dialect_region}")
            matching = [z for z in country_zones if _zone_offset_hours(z, at) == offset]
            if matching:
                zone_best = matching[0]
            else:
                # Dialect is a strong prior; keep its primary zone but flag the drift.
                zone_best = country_zones[0]
                signals.append("offset_dialect_mismatch")

    # 3) Candidate list + confidence.
    candidates = country_zones or _OFFSET_SAMPLE_ZONES.get(offset, [])
    if zone_best and _zone_offset_hours(zone_best, at) == offset and gated:
        confidence = "high"
    elif zone_best or gated:
        confidence = "medium"
    else:
        confidence = "low"
    if total_messages < _THIN_ACTOR_MESSAGES and confidence == "high":
        confidence = "medium"
    if total_messages < _THIN_ACTOR_MESSAGES and not gated:
        confidence = "low"

    return InferredTz(
        offset_hours=offset,
        zone_best=zone_best,
        zone_candidates=candidates,
        confidence=confidence,
        supporting_signals=signals,
        local_active_window=_shift_window(_active_window_utc(quiet_utc), offset),
        quiet_window_utc=quiet_utc,
    )
