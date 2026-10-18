# SPDX-License-Identifier: AGPL-3.0-or-later
"""Known runtime settings (app_setting keys) — the registry shared by the admin API
and the services that consume them.

Each key declares a default + a validator/coercer so the admin API rejects garbage and
unknown keys instead of letting anything be written, and so a consumer always has a sane
value even before an admin ever sets one. Values are stored as strings (see
AppSettingTable); the coercer is the single place that parses them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

# --- keys ---
TELEGRAM_ATTACHMENT_MAX_BYTES = "telegram.attachment_max_bytes"
# Max shell-attachment blobs each Telegram collector re-fetches per tick during backfill.
# 0 = OFF (the default): backfill is held until an admin raises it, which also throttles
# the re-pull rate through the live covert session (N per tick).
TELEGRAM_ATTACHMENT_BACKFILL_PER_TICK = "telegram.attachment_backfill_per_tick"


def _coerce_nonneg_int(raw: str) -> str:
    n = int(raw)  # raises ValueError on non-int
    if n < 0:
        raise ValueError("must be >= 0")
    return str(n)


@dataclass(frozen=True)
class SettingSpec:
    default: str
    coerce: Callable[[str], str]
    description: str


SETTINGS: dict[str, SettingSpec] = {
    TELEGRAM_ATTACHMENT_MAX_BYTES: SettingSpec(
        default=str(3 * 1024 * 1024),  # 3 MiB
        coerce=_coerce_nonneg_int,
        description="Max attachment size (bytes) the Telegram collector downloads and stores. "
        "Larger files keep metadata + a retrieval link only. 0 disables downloads.",
    ),
    TELEGRAM_ATTACHMENT_BACKFILL_PER_TICK: SettingSpec(
        default="0",
        coerce=_coerce_nonneg_int,
        description="Shell attachments each Telegram collector re-fetches per tick (backfill). "
        "0 = off (held). Raise it to start/throttle re-pulling historical media.",
    ),
}


def is_known(key: str) -> bool:
    return key in SETTINGS


def default_value(key: str) -> str:
    return SETTINGS[key].default


def validate_value(key: str, raw: str) -> str:
    """Coerce/validate ``raw`` for ``key``; raises ValueError on a bad value or key."""
    if key not in SETTINGS:
        raise ValueError(f"unknown setting {key!r}")
    return SETTINGS[key].coerce(raw)


__all__ = [
    "SETTINGS",
    "TELEGRAM_ATTACHMENT_BACKFILL_PER_TICK",
    "TELEGRAM_ATTACHMENT_MAX_BYTES",
    "SettingSpec",
    "default_value",
    "is_known",
    "validate_value",
]
