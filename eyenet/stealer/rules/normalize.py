"""Normalize verb catalog. Byte-parity with ``normalize.js``.

Each verb is a pure string-to-string function applied to one field.
A verb that fails (parse error, no match) DROPS the field silently.

replace_re2 uses google-re2 for ReDoS safety, matching the AdGuard
RE2-wasm engine on the browser side.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import re2

from eyenet.stealer.rules.types import NormalizeStep

_RE2_MAX_MEM = 8 * 1024 * 1024


def apply_normalize(
    fields: dict[str, Any],
    steps: list[NormalizeStep],
) -> dict[str, Any]:
    out = dict(fields)
    for step in steps:
        f = step["field"]
        if f not in out or out[f] is None:
            continue
        raw = str(out[f])
        nxt = _run_verb(step, raw)
        if nxt is None:
            out.pop(f, None)
        else:
            out[f] = nxt
    return out


def _run_verb(step: NormalizeStep, raw: str) -> str | int | None:
    verb = step["verb"]
    if verb == "strip_whitespace":
        return raw.strip()
    if verb == "lowercase":
        return raw.lower()
    if verb == "uppercase":
        return raw.upper()
    if verb == "truncate":
        n = step.get("max_len", 0)
        if n <= 0:
            return raw
        return raw[:n] if len(raw) > n else raw
    if verb == "int_from_string":
        m = re2.search(r"-?\d+", raw)
        if not m:
            return None
        try:
            return int(m.group(0))
        except ValueError:
            return None
    if verb == "replace_re2":
        pattern = step.get("pattern")
        if not pattern:
            return raw
        try:
            # google-re2 enforces linear-time matching; max_mem bounds compile.
            opts = re2.Options()
            opts.max_mem = _RE2_MAX_MEM
            re_compiled = re2.compile(pattern, options=opts)
            return re_compiled.sub(step.get("replacement", ""), raw)
        except Exception:
            return None
    if verb == "date_parse":
        return _parse_date(raw, step.get("format", "iso8601"))
    return None


def _parse_date(raw: str, fmt: str) -> str | None:
    if fmt == "epoch_seconds":
        try:
            n = int(raw)
        except ValueError:
            return None
        dt = datetime.fromtimestamp(n, tz=timezone.utc)
    else:
        # iso8601 / rfc2822: try both; emit canonical ISO back.
        from email.utils import parsedate_to_datetime
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            try:
                dt = parsedate_to_datetime(raw)
            except (TypeError, ValueError):
                return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    # Both engines drop fractional seconds before the trailing Z for parity.
    dt = dt.astimezone(timezone.utc).replace(microsecond=0)
    return dt.isoformat().replace("+00:00", "Z")
