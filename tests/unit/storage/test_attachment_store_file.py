# SPDX-License-Identifier: AGPL-3.0-or-later
"""store_attachment_file: streaming (temp-file) blob store — hash, move, idempotency."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from eyenet.contracts.enums import SourceKind
from eyenet.storage.attachments import store_attachment, store_attachment_file

pytestmark = pytest.mark.unit


def _temp_blob(tmp_root: Path, data: bytes) -> Path:
    tmp_root.mkdir(parents=True, exist_ok=True)
    p = tmp_root / "incoming.download"
    p.write_bytes(data)
    return p


def test_hashes_moves_and_matches_bytes_variant(tmp_path: Path) -> None:
    data = b"stealer archive bytes" * 1000
    src = _temp_blob(tmp_path / "attachments", data)

    sha, uri = store_attachment_file(
        tmp_path, src, source=SourceKind.TELEGRAM, instance_id="col-0"
    )

    # Correct content-addressed hash, blob on disk with the right bytes.
    assert sha == hashlib.sha256(data).hexdigest()
    assert Path(uri).exists()
    assert Path(uri).read_bytes() == data
    # Same digest the bytes variant would produce (one store, two entry points).
    bytes_sha, _ = store_attachment(tmp_path, data, source=SourceKind.TELEGRAM, instance_id="col-0")
    assert sha == bytes_sha
    # The temp file was consumed by the move.
    assert not src.exists()


def test_idempotent_on_sha_drops_duplicate_temp(tmp_path: Path) -> None:
    data = b"dup" * 500
    first = _temp_blob(tmp_path / "attachments", data)
    sha1, uri1 = store_attachment_file(
        tmp_path, first, source=SourceKind.TELEGRAM, instance_id="col-0"
    )

    # A second temp with identical bytes: same sha, same destination, temp removed.
    second = tmp_path / "attachments" / "again.download"
    second.write_bytes(data)
    sha2, uri2 = store_attachment_file(
        tmp_path, second, source=SourceKind.TELEGRAM, instance_id="col-0"
    )

    assert sha1 == sha2
    assert uri1 == uri2
    assert not second.exists()  # duplicate temp dropped, canonical blob untouched
    assert Path(uri1).read_bytes() == data
