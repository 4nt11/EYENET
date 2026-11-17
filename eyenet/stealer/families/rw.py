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


def families_dir() -> Path:
    return Path(os.environ.get("EYENET_STEALER_FAMILIES_DIR") or _VENDORED)


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
    for req in ("slug", "name", "status"):
        if req not in family:
            raise ValueError(f"family missing required field: {req}")
    _enforce_slug(family["slug"])
    if family["status"] not in _VALID_STATUSES:
        raise ValueError(f"family.status must be one of {sorted(_VALID_STATUSES)}")


def _atomic_write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8",
        dir=str(path.parent), prefix=f".{path.stem}.", suffix=".tmp",
        delete=False,
    ) as tmp:
        tmp.write(body)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_name = tmp.name
    os.replace(tmp_name, path)
