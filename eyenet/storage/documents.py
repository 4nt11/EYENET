"""Sharded on-disk document blob store (M10 slice 7).

A sibling of `storage/attachments.py:store_attachment`. EYENET is
operator-grade evidence ([[feedback_operator_grade_evidence]]): the raw
uploaded bytes are retained on disk so the operator can re-derive hashes and
produce evidentiary copies.

Layout (under the EYENET data dir):

    data/documents/<sha256[:2]>/<sha256>.bin

Unlike attachments there is no `<source>/<instance_id>` prefix — a document is
operator-uploaded, not collected from a platform. The two-char prefix shard
keeps any one directory bounded.

The returned `sha256` is the HOST-SIDE custody hash over the RAW bytes — never
over jail output, never over extracted text (which varies by extractor
version). This is the value that goes into `DocumentTable.sha256`.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


def document_root(data_dir: Path) -> Path:
    """Return the root directory under which all document blobs live."""

    return data_dir / "documents"


def store_document(data_dir: Path, payload: bytes) -> tuple[str, str]:
    """Persist `payload` to the sharded store. Idempotent on sha256.

    Returns `(sha256_hex, storage_uri)`. `storage_uri` is an absolute
    filesystem path string suitable for direct use in `DocumentTable`.

    Idempotency: if a blob with the same sha256 already exists, the bytes are
    NOT rewritten — re-ingest of the same file is cheap and inode counts stay
    bounded by the universe of distinct documents, not upload events.
    """

    digest = hashlib.sha256(payload).hexdigest()
    dest_dir = document_root(data_dir) / digest[:2]
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{digest}.bin"
    if not dest.exists():
        # Write to a tempfile + rename so a crashed write never leaves a
        # half-written blob at the canonical path.
        tmp = dest.with_suffix(".bin.partial")
        tmp.write_bytes(payload)
        tmp.rename(dest)
    return digest, str(dest)


__all__ = ["document_root", "store_document"]
