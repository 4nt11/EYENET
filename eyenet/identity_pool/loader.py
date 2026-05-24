"""TOML loader for `identities.toml`.

PLAN §6.1: pool config lives outside the repo (gitignored, age-encrypted at
rest in production). The loader's job is to validate the shape and refuse
to load anything that points at a non-existent session file — silent
config errors here become collector-launch surprises later.
"""

from __future__ import annotations

import tomllib
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from eyenet.contracts.enums import IdentityState, SourceKind


class IdentityFileEntry(BaseModel):
    """One identity row in `identities.toml`."""

    model_config = ConfigDict(extra="forbid")

    name: str
    source: SourceKind
    session_path: str = ""
    proxy_uri: str | None = None
    cooldown_seconds: int = 21_600
    last_used_at: datetime | None = None
    state: IdentityState = IdentityState.AVAILABLE
    notes: str | None = None

    # Telegram-specific (required when source=telegram)
    telegram_api_id: int | None = None
    telegram_api_hash: str | None = None
    # Groups/channels to monitor. Empty list = all dialogs the identity is in.
    # Accepts @username strings or numeric chat IDs (as strings).
    monitor_groups: list[str] = Field(default_factory=list)

    # Matrix-specific (required when source=matrix). Access token is sensitive
    # — file is gitignored + age-encrypted at rest per PLAN §6.1, same as
    # telegram_api_hash. No session file: nio caches state under the
    # collector's data dir, not via a single .session blob.
    matrix_homeserver_url: str | None = None
    matrix_user_id: str | None = None
    matrix_access_token: str | None = None
    matrix_device_id: str | None = None
    # Room ids (!abc:server) or aliases (#room:server). Empty = no monitoring.
    matrix_monitor_rooms: list[str] = Field(default_factory=list)
    # E2EE device store path. nio persists Olm sessions, Megolm inbound
    # group sessions, and the sync token here. Empty/None = default to
    # `<eyenet_data_dir>/matrix/<identity_name>/store/`, populated by
    # MatrixCollector at start. The directory contains long-lived crypto
    # state; do NOT include in any future `eyenet purge`.
    matrix_device_store_path: str | None = None

    @model_validator(mode="after")
    def _default_session_path(self) -> IdentityFileEntry:
        if not self.session_path:
            default = Path.home() / ".local" / "share" / "eyenet" / "sessions" / self.name
            self.session_path = str(default)
        return self


def _uses_session_file(source: SourceKind) -> bool:
    """Return True if the source kind persists auth as a session file on disk.

    Telegram (MTProto via telethon) does. Matrix does not — nio holds the
    access_token in memory; the operator stores it directly in the TOML.
    """

    return source == SourceKind.TELEGRAM


class IdentityFile(BaseModel):
    """Parsed `identities.toml` shape."""

    model_config = ConfigDict(extra="forbid")

    identities: list[IdentityFileEntry] = Field(default_factory=list)


def load(path: Path, *, check_session_files: bool = True) -> IdentityFile:
    """Load and validate `identities.toml`."""

    if not path.exists():
        raise FileNotFoundError(f"identities file not found: {path}")
    raw = tomllib.loads(path.read_text("utf-8"))
    parsed = IdentityFile.model_validate(raw)
    if check_session_files:
        for entry in parsed.identities:
            if not _uses_session_file(entry.source):
                continue
            session = Path(entry.session_path)
            if not session.exists():
                raise ValueError(f"identity {entry.name!r} session_path missing: {session}")
    # Disallow duplicate names.
    seen: set[str] = set()
    for entry in parsed.identities:
        if entry.name in seen:
            raise ValueError(f"duplicate identity name: {entry.name!r}")
        seen.add(entry.name)
    return parsed


def dump(model: IdentityFile, path: Path) -> None:
    """Write the file back. Used on `release` for state persistence."""

    lines: list[str] = []
    for entry in model.identities:
        lines.append("[[identities]]")
        lines.append(f"name = {_q(entry.name)}")
        lines.append(f"source = {_q(entry.source.value)}")
        lines.append(f"session_path = {_q(entry.session_path)}")
        if entry.proxy_uri is not None:
            lines.append(f"proxy_uri = {_q(entry.proxy_uri)}")
        lines.append(f"cooldown_seconds = {entry.cooldown_seconds}")
        if entry.last_used_at is not None:
            lines.append(f"last_used_at = {entry.last_used_at.isoformat()!r}")
        lines.append(f"state = {_q(entry.state.value)}")
        if entry.notes is not None:
            lines.append(f"notes = {_q(entry.notes)}")
        if entry.telegram_api_id is not None:
            lines.append(f"telegram_api_id = {entry.telegram_api_id}")
        if entry.telegram_api_hash is not None:
            lines.append(f"telegram_api_hash = {_q(entry.telegram_api_hash)}")
        if entry.monitor_groups:
            groups_str = ", ".join(f'"{g}"' for g in entry.monitor_groups)
            lines.append(f"monitor_groups = [{groups_str}]")
        lines.extend(_matrix_lines(entry))
        lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _matrix_lines(entry: IdentityFileEntry) -> list[str]:
    out: list[str] = []
    if entry.matrix_homeserver_url is not None:
        out.append(f"matrix_homeserver_url = {_q(entry.matrix_homeserver_url)}")
    if entry.matrix_user_id is not None:
        out.append(f"matrix_user_id = {_q(entry.matrix_user_id)}")
    if entry.matrix_access_token is not None:
        out.append(f"matrix_access_token = {_q(entry.matrix_access_token)}")
    if entry.matrix_device_id is not None:
        out.append(f"matrix_device_id = {_q(entry.matrix_device_id)}")
    if entry.matrix_monitor_rooms:
        rooms_str = ", ".join(f'"{r}"' for r in entry.matrix_monitor_rooms)
        out.append(f"matrix_monitor_rooms = [{rooms_str}]")
    if entry.matrix_device_store_path is not None:
        out.append(f"matrix_device_store_path = {_q(entry.matrix_device_store_path)}")
    return out


def _q(s: str) -> str:
    escaped = s.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


__all__ = ["IdentityFile", "IdentityFileEntry", "dump", "load"]
