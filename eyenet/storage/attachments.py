"""Sharded on-disk attachment blob store.

EYENET is operator-grade evidence ([[feedback_operator_grade_evidence]]):
attachment binaries are retained on disk so the operator can re-derive
hashes, inspect contents, and produce evidentiary copies after the source
platform purges its own media.

Layout (under the EYENET data dir):

    data/attachments/<source>/<instance_id>/<sha256[:2]>/<sha256>.bin

The two-char prefix shard keeps any one directory from accumulating more
than ~256 siblings before the next level fans out.

Matrix is the first collector wired through this helper. Telegram remains
metadata-only in M8 — when it adopts the helper, no schema change is
required; only `storage_uri` flips from None to the returned path.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from eyenet.contracts.enums import SourceKind

# Read chunk for the incremental hash of an already-downloaded file (store_attachment_file).
_HASH_CHUNK = 1024 * 1024  # 1 MiB


def attachment_root(data_dir: Path) -> Path:
    """Return the root directory under which all attachment blobs live."""

    return data_dir / "attachments"


def store_attachment(
    data_dir: Path,
    payload: bytes,
    *,
    source: SourceKind,
    instance_id: str,
) -> tuple[str, str]:
    """Persist `payload` to the sharded store. Idempotent on sha256.

    Returns `(sha256_hex, storage_uri)`. `storage_uri` is an absolute
    filesystem path string suitable for direct use in `AttachmentTable`.

    Idempotency: if a blob with the same sha256 already exists, the bytes
    are NOT rewritten. This makes re-ingest cheap and keeps inode counts
    bounded by the universe of distinct attachments, not events.
    """

    digest = hashlib.sha256(payload).hexdigest()
    shard = digest[:2]
    dest_dir = attachment_root(data_dir) / source.value / instance_id / shard
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{digest}.bin"
    if not dest.exists():
        # Write to a tempfile + rename so a crashed write never leaves a
        # half-written blob at the canonical path.
        tmp = dest.with_suffix(".bin.partial")
        tmp.write_bytes(payload)
        tmp.rename(dest)
    return digest, str(dest)


def store_attachment_file(
    data_dir: Path,
    src_path: Path,
    *,
    source: SourceKind,
    instance_id: str,
) -> tuple[str, str]:
    """Persist an ALREADY-DOWNLOADED temp file into the sharded store by streaming.

    The streaming counterpart of :func:`store_attachment`: the caller downloads to
    `src_path` on disk (never a RAM `bytes` buffer), and this hashes it in chunks
    and MOVES it into the content-addressed location. Use it for large blobs — the
    stealer cap-bypass pulls multi-GB archives that must never be held whole in RAM.

    Returns `(sha256_hex, storage_uri)`. `src_path` is consumed: moved into place,
    or unlinked on an idempotent sha hit. `src_path` MUST be on the same filesystem
    as the attachment store (put it under `data_dir`) so the move is an atomic
    rename, not a copy. Idempotent on sha256, like :func:`store_attachment`.
    """
    h = hashlib.sha256()
    with src_path.open("rb") as f:
        while chunk := f.read(_HASH_CHUNK):
            h.update(chunk)
    digest = h.hexdigest()
    shard = digest[:2]
    dest_dir = attachment_root(data_dir) / source.value / instance_id / shard
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{digest}.bin"
    if dest.exists():
        src_path.unlink(missing_ok=True)  # already stored — drop the duplicate temp
    else:
        src_path.replace(dest)  # atomic rename within the filesystem
    return digest, str(dest)


__all__ = ["attachment_root", "store_attachment", "store_attachment_file"]
