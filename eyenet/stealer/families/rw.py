"""Read/write operations for the on-disk stealer family catalog.

Mirrors ``eyenet.stealer.rules.catalog.rw`` so the shape stays familiar:
atomic write (temp + fsync + rename), slug allow-list regex for path
safety, env-var override of the active directory.

Slug conventions follow family catalog style (underscore-separated,
lowercase); the regex is intentionally the same as the rules one so an
operator who learns one never has to learn the other.
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any

import yaml

_log = logging.getLogger(__name__)
_VENDORED = Path(__file__).resolve().parent
_SLUG_RX = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_VALID_STATUSES = frozenset({"active", "retired", "dormant", "new", "suspected"})
# Discriminator so classification does not confuse a stealer (lumma) with a
# content shape (cookies) or a tool (anydesk). Only `kind: stealer` entries
# are classification targets; the rest are metadata the rule authors lean on.
# See development/STEALER_FAMILY_CLASSIFIER_DESIGN.md for the full picture.
_VALID_KINDS = frozenset({"stealer", "content", "tool", "combolist", "leak_pack"})
# Signal weight keys recognized on the optional per-family `signal_weights`
# override. Unknown keys fail the load loud, no silent typo drift.
_VALID_SIGNAL_WEIGHT_KEYS = frozenset(
    {"sig_file", "sig_path", "sig_rule", "build_tag", "anti_file", "anti_rule"}
)
# Current schema version. Bump when a new required field lands and we need
# a migration pass; the loader can gate off the version for compatibility
# shims.
_SCHEMA_VERSION = 2


def families_dir() -> Path:
    """Return the active families directory (env-overridable).

    When the env var points at a directory distinct from the vendored
    one, lazily seed it from the vendored defaults so a shared volume
    boots with the live catalog. Idempotent + never overwrites; see
    _ensure_seeded. The rules-side rw mirrors this logic."""
    env = os.environ.get("EYENET_STEALER_FAMILIES_DIR")
    if env:
        target = Path(env)
        if target.resolve() != _VENDORED.resolve():
            _ensure_seeded(target)
        return target
    return _VENDORED


_seeded_targets: set[str] = set()


def _ensure_seeded(target: Path) -> None:
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
        _log.warning("stealer.families.seed_failed target=%s error=%s", target, exc)


def list_family_slugs() -> list[str]:
    return sorted(p.stem for p in families_dir().glob("*.yaml"))


def read_family(slug: str) -> dict[str, Any]:
    _enforce_slug(slug)
    p = _resolve_family_path(slug)
    if not p.is_file():
        raise FileNotFoundError(slug)
    doc = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError(f"{slug}: file is not a family document")
    return doc


def write_family(family: dict[str, Any], *, allow_overwrite: bool) -> dict[str, Any]:
    _validate_family_shape(family)
    slug = family["slug"]
    p = _resolve_family_path(slug)
    if p.exists() and not allow_overwrite:
        raise FileExistsError(slug)
    body = yaml.safe_dump(family, sort_keys=False, allow_unicode=True)
    _atomic_write(p, body)
    return family


def delete_family(slug: str) -> None:
    _enforce_slug(slug)
    p = _resolve_family_path(slug)
    if not p.is_file():
        raise FileNotFoundError(slug)
    p.unlink()


def _enforce_slug(slug: str) -> None:
    if not isinstance(slug, str) or not _SLUG_RX.match(slug):
        raise ValueError(f"invalid slug (must match {_SLUG_RX.pattern}): {slug!r}")


def _resolve_family_path(slug: str) -> Path:
    _enforce_slug(slug)
    base = families_dir().resolve()
    p = (base / f"{slug}.yaml").resolve()
    if p.parent != base:
        raise ValueError(f"slug escaped catalog directory: {slug!r}")
    return p


def _validate_family_shape(family: dict[str, Any]) -> None:
    for req in ("slug", "name", "status", "kind"):
        if req not in family:
            raise ValueError(f"family missing required field: {req}")
    _enforce_slug(family["slug"])
    if family["status"] not in _VALID_STATUSES:
        raise ValueError(f"family.status must be one of {sorted(_VALID_STATUSES)}")
    if family["kind"] not in _VALID_KINDS:
        raise ValueError(f"family.kind must be one of {sorted(_VALID_KINDS)}")
    _validate_classifier_signals(family)


def _validate_classifier_signals(family: dict[str, Any]) -> None:
    """Shape-check the optional signal fields used by the per-victim family
    classifier (Phase 2). All fields are optional: a family with none of
    them still loads, it just will not be a confident classification target.
    Unknown signal-weight keys fail loud so a typo does not silently
    degrade scoring."""
    slug = family["slug"]
    for list_field in (
        "signature_paths",
        "signature_rule_ids",
        "antisignature_files",
        "antisignature_rule_ids",
    ):
        v = family.get(list_field)
        if v is None:
            continue
        if not isinstance(v, list) or not all(isinstance(x, str) and x for x in v):
            raise ValueError(f"{slug}.{list_field} must be a list of non-empty strings")
    build_tag = family.get("build_tag_regex")
    if build_tag is not None:
        if not isinstance(build_tag, str) or not build_tag:
            raise ValueError(f"{slug}.build_tag_regex must be a non-empty string")
        try:
            re.compile(build_tag)
        except re.error as exc:
            raise ValueError(f"{slug}.build_tag_regex is not a valid regex: {exc}") from exc
    floor = family.get("confidence_floor")
    if floor is not None and (not isinstance(floor, int | float) or not 0.0 <= float(floor) <= 1.0):
        raise ValueError(f"{slug}.confidence_floor must be a float in [0, 1]")
    weights = family.get("signal_weights")
    if weights is not None:
        if not isinstance(weights, dict):
            raise ValueError(f"{slug}.signal_weights must be a mapping")
        for k, v in weights.items():
            if k not in _VALID_SIGNAL_WEIGHT_KEYS:
                raise ValueError(
                    f"{slug}.signal_weights.{k} is not one of {sorted(_VALID_SIGNAL_WEIGHT_KEYS)}"
                )
            if not isinstance(v, int | float):
                raise ValueError(f"{slug}.signal_weights.{k} must be a number")


def _atomic_write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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
