# SPDX-License-Identifier: AGPL-3.0-or-later
"""Convert an uploaded Telegram Desktop ``tdata`` folder into a Telethon
``.session`` blob, so a bought tdata account drops into the SAME provisioning
path as a ``.session`` upload (``_provision._materialize_secret``).

SECURITY: the archive is attacker-controlled operator input, and extraction is
the whole risk surface, so it is hardened against the classic archive attacks:

  - path traversal / zip-slip: every member path is resolved and confined under
    the extraction root; absolute paths, drive letters, and ``..`` escapes are
    rejected before a single byte is written.
  - symlink / hardlink / device / FIFO escapes (tar): only regular files and
    directories are allowed; anything else is rejected.
  - zip-bomb: hard caps on entry count, per-file size, total uncompressed size,
    and the compression ratio. Writes stream through a running cap, so a header
    that LIES about its size still aborts mid-extraction, not after.

We never call ``extractall``/``extract`` (which can follow member-declared
paths); we compute a confined destination ourselves and stream into it.

OPSEC: conversion is OFFLINE. opentele's ``UseCurrentSession`` reuses the tdata
auth key to write a Telethon session WITHOUT a network login. We NEVER
``.connect()`` here - a login from the API host's datacenter IP is exactly the
event that bans a freshly-bought account. The session is proven live later, when
the collector dials Telegram THROUGH the identity's proxy.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import shutil
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import IO

from eyenet.identity_pool._provision import (
    SessionValidationError,
    _telegram_string_from_blob,
)

# Compressed upload cap. A tdata folder for a fresh account is a few MB; this
# rejects a mistaken bulk/wrong upload without truncating a legitimate one.
_MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
# Uncompressed guards. Total across all members, and per single member. A normal
# tdata (no media cache) is well under these; a batch with heavy cache should be
# trimmed before upload rather than silently inflating the box.
_MAX_TOTAL_BYTES = 200 * 1024 * 1024
_MAX_FILE_BYTES = 50 * 1024 * 1024
# Entry-count and ratio ceilings: a zip bomb is either many tiny entries or one
# wildly over-compressed entry. Both trip here.
_MAX_ENTRIES = 5_000
_MAX_RATIO = 120
_CHUNK = 64 * 1024


@dataclass(frozen=True)
class TdataSession:
    """The offline conversion result.

    ``session_blob`` is Telethon ``.session`` SQLite bytes - byte-identical in
    shape to a ``.session`` upload, so it flows through the unchanged provisioning
    path. ``api_id``/``api_hash`` are the credentials the session is authorized
    under; the identity MUST be stored with them or the collector's first connect
    mismatches the auth key and re-auths (ban risk)."""

    session_blob: bytes
    api_id: int
    api_hash: str


def _safe_member_path(base: Path, name: str) -> Path:
    """Resolve an archive member name to a path CONFINED under ``base``.

    Rejects absolute paths, Windows drive letters, and any ``..`` escape. This is
    the zip-slip guard; it runs for every member before any write."""
    norm = name.replace("\\", "/")
    rel = PurePosixPath(norm)
    if rel.is_absolute() or norm[1:2] == ":":  # absolute, or a Windows drive letter
        raise SessionValidationError("archive_absolute_path")
    target = (base / Path(*rel.parts)).resolve()
    base_r = base.resolve()
    if target != base_r and base_r not in target.parents:
        raise SessionValidationError("archive_path_escape")
    return target


def _stream_to(src: IO[bytes], target: Path, running_total: int) -> int:
    """Copy ``src`` -> ``target`` in bounded chunks, enforcing per-file and total
    caps DURING the copy (a declared size can lie; the stream can't). Returns the
    new running total."""
    target.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    total = running_total
    with target.open("wb") as out:
        while True:
            chunk = src.read(_CHUNK)
            if not chunk:
                break
            written += len(chunk)
            total += len(chunk)
            if written > _MAX_FILE_BYTES:
                raise SessionValidationError("archive_file_too_large")
            if total > _MAX_TOTAL_BYTES:
                raise SessionValidationError("archive_total_too_large")
            out.write(chunk)
    return total


def _extract_zip(data: bytes, dest: Path) -> None:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        infos = zf.infolist()
        if len(infos) > _MAX_ENTRIES:
            raise SessionValidationError("archive_too_many_entries")
        total = 0
        for info in infos:
            if info.filename.endswith("/"):
                _safe_member_path(dest, info.filename)  # validate dir name, created lazily
                continue
            # Fast header-based rejects before reading (the streaming cap below is
            # the real defense; these just fail an obvious bomb cheaply).
            if info.file_size > _MAX_FILE_BYTES:
                raise SessionValidationError("archive_file_too_large")
            if info.compress_size and info.file_size / info.compress_size > _MAX_RATIO:
                raise SessionValidationError("archive_ratio_suspicious")
            target = _safe_member_path(dest, info.filename)
            with zf.open(info) as src:
                total = _stream_to(src, target, total)


def _extract_tar(data: bytes, dest: Path) -> None:
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as tf:
        total = 0
        count = 0
        for member in tf:
            count += 1
            if count > _MAX_ENTRIES:
                raise SessionValidationError("archive_too_many_entries")
            if member.isdir():
                _safe_member_path(dest, member.name)
                continue
            # Regular files ONLY. isfile() is False for symlink/hardlink/char/block
            # /fifo, every one of which is an escape or resource vector in a tar.
            if not member.isfile():
                raise SessionValidationError("archive_unsafe_member_type")
            if member.size > _MAX_FILE_BYTES:
                raise SessionValidationError("archive_file_too_large")
            target = _safe_member_path(dest, member.name)
            src = tf.extractfile(member)
            if src is None:
                raise SessionValidationError("archive_unreadable_member")
            with src:
                total = _stream_to(src, target, total)


def extract_archive_safely(archive: bytes, dest: Path) -> None:
    """Extract a zip or tar(.gz/.bz2/.xz) archive into ``dest`` with every archive
    guard applied. Raises :class:`SessionValidationError` (-> 422) on any breach."""
    if len(archive) > _MAX_ARCHIVE_BYTES:
        raise SessionValidationError("archive_too_large")
    if zipfile.is_zipfile(io.BytesIO(archive)):
        _extract_zip(archive, dest)
        return
    is_tar = False
    with contextlib.suppress(tarfile.TarError, OSError):
        is_tar = tarfile.is_tarfile(io.BytesIO(archive))
    if is_tar:
        _extract_tar(archive, dest)
        return
    raise SessionValidationError("unsupported_archive_format")


def _find_tdata_root(root: Path) -> Path:
    """Locate the tdata folder within the extracted tree.

    The archive may wrap it (``tdata/``, ``Account/tdata/``) or be the tdata
    contents directly. ``key_datas`` is Telegram Desktop's local-key file and the
    reliable marker; the shallowest match is the real root (not a nested copy)."""
    candidates = [p.parent for p in root.rglob("key_datas") if p.is_file()]
    if not candidates:
        raise SessionValidationError("no_tdata_found")
    return min(candidates, key=lambda d: len(d.relative_to(root).parts))


async def tdata_archive_to_session(archive: bytes) -> TdataSession:
    """Archive bytes -> validated, offline-converted Telethon ``.session`` + its
    api credentials. The extraction (blocking, bounded) runs in a worker thread;
    the opentele conversion is awaited. The plaintext session lives only in a temp
    dir that is always torn down - it never persists server-side (as with the
    ``.session`` upload)."""
    tmp = Path(tempfile.mkdtemp(prefix="eyenet-tdata-"))
    try:
        extract_dir = tmp / "x"
        extract_dir.mkdir()
        await asyncio.to_thread(extract_archive_safely, archive, extract_dir)
        tdata_root = _find_tdata_root(extract_dir)
        return await _convert_offline(tdata_root, tmp / "out.session")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


async def _convert_offline(tdata_root: Path, session_path: Path) -> TdataSession:
    # Lazy import: opentele (and its pyrogram dep) is only needed on this path,
    # mirroring curl-cffi in the forum collector. Keeps it out of hot imports.
    try:
        from opentele.api import API, UseCurrentSession  # noqa: PLC0415 - lazy: tdata path only
        from opentele.td import TDesktop  # noqa: PLC0415 - lazy: tdata path only
    except ImportError as exc:  # pragma: no cover - dep presence is a deploy concern
        raise SessionValidationError("opentele_not_installed") from exc

    # TDesktop parses the tdata; a locked (local-passcode) or corrupt folder fails
    # here. Broad catch at a trust boundary, re-raised as operator error (422).
    try:
        tdesk = TDesktop(str(tdata_root))
    except Exception as exc:  # untrusted tdata -> wrap any parse failure to 422
        raise SessionValidationError("tdata_unreadable_or_locked") from exc
    if not tdesk.isLoaded() or len(tdesk.accounts) == 0:
        raise SessionValidationError("tdata_no_account")

    api = API.TelegramDesktop
    try:
        # OFFLINE: reuse the tdata auth key; no login, no network. We never
        # .connect() - that would be a datacenter-IP login and a ban trigger.
        client = await tdesk.ToTelethon(session=str(session_path), flag=UseCurrentSession, api=api)
    except Exception as exc:  # untrusted tdata -> wrap any conversion failure to 422
        raise SessionValidationError("tdata_conversion_failed") from exc
    # Release the sqlite handle before we read the file bytes (best-effort cleanup).
    with contextlib.suppress(Exception):
        client.session.close()

    blob = await asyncio.to_thread(session_path.read_bytes)
    # Reuse the EXACT validation the .session upload uses (auth_key must be present).
    _telegram_string_from_blob(blob)
    return TdataSession(
        session_blob=blob,
        api_id=int(api.api_id),
        api_hash=str(api.api_hash),
    )


__all__ = ["TdataSession", "extract_archive_safely", "tdata_archive_to_session"]
