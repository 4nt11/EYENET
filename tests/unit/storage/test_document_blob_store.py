"""``store_document`` — the host-side custody hash + sharded byte store."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from eyenet.storage.documents import document_root, store_document

pytestmark = pytest.mark.unit


def test_returns_correct_sha256_and_path(tmp_path: Path) -> None:
    payload = b"the quick brown fox"
    digest, uri = store_document(tmp_path, payload)
    assert digest == hashlib.sha256(payload).hexdigest()
    assert uri == str(document_root(tmp_path) / digest[:2] / f"{digest}.bin")
    assert Path(uri).read_bytes() == payload


def test_idempotent_does_not_rewrite(tmp_path: Path) -> None:
    payload = b"evidence"
    digest, uri = store_document(tmp_path, payload)
    first_mtime = Path(uri).stat().st_mtime_ns

    digest2, uri2 = store_document(tmp_path, payload)
    assert (digest2, uri2) == (digest, uri)
    # Existing blob is NOT rewritten (mtime unchanged).
    assert Path(uri).stat().st_mtime_ns == first_mtime


def test_no_partial_file_left_behind(tmp_path: Path) -> None:
    _, uri = store_document(tmp_path, b"data")
    partial = Path(uri).with_suffix(".bin.partial")
    assert not partial.exists()


def test_distinct_payloads_shard_independently(tmp_path: Path) -> None:
    d1, u1 = store_document(tmp_path, b"alpha")
    d2, u2 = store_document(tmp_path, b"beta")
    assert d1 != d2
    assert u1 != u2
    assert Path(u1).read_bytes() == b"alpha"
    assert Path(u2).read_bytes() == b"beta"
