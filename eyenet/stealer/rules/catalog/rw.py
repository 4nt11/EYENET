"""Read/write operations for the on-disk stealer rule catalog.

Vendored rules ship with the wheel at ``eyenet/stealer/rules/catalog/``.
The OPERATIVE catalog (edited via the HTTP API) lives at the path pointed
to by ``EYENET_STEALER_RULES_DIR``, defaulting to the vendored dir so
dev + tests just work.

Writes are atomic: validate -> write temp -> fsync -> rename. Slugs go
through a strict allow-list regex so a crafted id can't escape the
catalog directory.
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from eyenet.stealer.families import valid_slugs as _family_slugs

_log = logging.getLogger(__name__)
_VENDORED = Path(__file__).resolve().parent
_SLUG_RX = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_VALID_LAYERS = frozenset({"container", "content"})
_VALID_MATCH_TYPES = frozenset(
    {
        "folder",
        "regex",
        "delimiter",
        "template",
        "json",
        "yaml",
        "keyvalue",
        "keyvalue_ini",
    }
)


def rules_dir() -> Path:
    """Return the active catalog directory (env-overridable).

    When the env var points at a directory distinct from the vendored
    one (prod uses a shared /var/lib/eyenet/stealer-catalog/rules volume
    so API writes flow to the gotractor daemon via fsnotify), lazily
    seed it from the vendored defaults on first call per process. See
    _ensure_seeded; dev + tests on the default path are untouched."""
    env = os.environ.get("EYENET_STEALER_RULES_DIR")
    if env:
        target = Path(env)
        if target.resolve() != _VENDORED.resolve():
            _ensure_seeded(target)
        return target
    return _VENDORED


_seeded_targets: set[str] = set()


def _ensure_seeded(target: Path) -> None:
    """Seed ``target`` from the vendored catalog if it lacks any of the
    vendored files. Idempotent across process + concurrent-safe: a race
    between two callers can only re-copy the same files, never corrupt
    a partial write (atomic rename). Never overwrites: an operator edit
    in the shared volume wins over a fresher vendored copy, so a
    package upgrade does not stomp on live tunings. The matching CLI
    (future) handles explicit vendored-resync when operators want it."""
    key = str(target.resolve())
    if key in _seeded_targets:
        return
    _seeded_targets.add(key)
    try:
        target.mkdir(parents=True, exist_ok=True)
        existing = {p.name for p in target.glob("*.yaml")}
        for src in _VENDORED.glob("*.yaml"):
            if src.name in existing:
                continue
            body = src.read_text(encoding="utf-8")
            _atomic_write(target / src.name, body)
    except OSError as exc:
        _log.warning("stealer.rules.seed_failed target=%s error=%s", target, exc)


def list_rule_slugs() -> list[str]:
    return sorted(p.stem for p in rules_dir().glob("*.yaml"))


def read_rule(slug: str) -> dict[str, Any]:
    _enforce_slug(slug)
    p = _resolve_rule_path(slug)
    if not p.is_file():
        raise FileNotFoundError(slug)
    doc = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError(f"{slug}: file is not a rule document")
    return doc


def write_rule(rule: dict[str, Any], *, allow_overwrite: bool) -> dict[str, Any]:
    """Validate + atomically write a rule YAML. Returns the stored dict.

    Slug is derived from ``rule['id']`` and is also the filename stem,
    so creating two rules with the same id is impossible on disk.
    """
    _validate_rule_shape(rule)
    slug = rule["id"]
    p = _resolve_rule_path(slug)
    if p.exists() and not allow_overwrite:
        raise FileExistsError(slug)
    body = yaml.safe_dump(rule, sort_keys=False, allow_unicode=True)
    _atomic_write(p, body)
    return rule


def delete_rule(slug: str) -> None:
    _enforce_slug(slug)
    p = _resolve_rule_path(slug)
    if not p.is_file():
        raise FileNotFoundError(slug)
    p.unlink()


def _enforce_slug(slug: str) -> None:
    if not isinstance(slug, str) or not _SLUG_RX.match(slug):
        raise ValueError(f"invalid slug (must match {_SLUG_RX.pattern}): {slug!r}")


def _resolve_rule_path(slug: str) -> Path:
    _enforce_slug(slug)
    base = rules_dir().resolve()
    p = (base / f"{slug}.yaml").resolve()
    # Path-traversal defence: the resolved file MUST live directly inside base.
    if p.parent != base:
        raise ValueError(f"slug escaped catalog directory: {slug!r}")
    return p


def _validate_rule_shape(rule: dict[str, Any]) -> None:
    for req in ("id", "version", "layer", "family", "priority", "match"):
        if req not in rule:
            raise ValueError(f"rule missing required field: {req}")
    _enforce_slug(rule["id"])
    if rule["layer"] not in _VALID_LAYERS:
        raise ValueError(f"rule.layer must be one of {sorted(_VALID_LAYERS)}")
    match = rule.get("match") or {}
    if not isinstance(match, dict) or match.get("type") not in _VALID_MATCH_TYPES:
        raise ValueError(f"rule.match.type must be one of {sorted(_VALID_MATCH_TYPES)}")
    if not isinstance(rule["priority"], int):
        raise ValueError("rule.priority must be an integer")
    fam = rule["family"]
    if fam not in _family_slugs():
        _log.warning(
            "rule %r references unknown family %r (editor should surface this)",
            rule["id"],
            fam,
        )


def _atomic_write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # NamedTemporaryFile on the same filesystem so os.replace is atomic.
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=str(path.parent),
        prefix=f".{path.stem}.",
        suffix=".tmp",
        delete=False,
    ) as tmp:
        tmp.write(body)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_name = tmp.name
    Path(tmp_name).replace(path)
