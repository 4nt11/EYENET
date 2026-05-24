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


__all__ = ["attachment_root", "store_attachment"]
