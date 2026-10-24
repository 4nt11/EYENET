# SPDX-License-Identifier: AGPL-3.0-or-later
"""ULP processing pipeline: encrypted archive blob → creds in ClickHouse.

Pure of EYENET storage/bus — takes a blob path + password candidates, does
decrypt → extract → ulpextract → batched ClickHouse insert, and returns a result.
Synchronous (subprocess-heavy, CPU/IO bound); the service runs it via
``asyncio.to_thread`` so it never blocks the event loop. Every external tool runs as
a SUBPROCESS: process isolation keeps a panic/OOM on an attacker-controlled archive
out of the service's address space.
"""

from __future__ import annotations

import shutil
import subprocess  # nosec B404 — fixed tools (unrar/ulpextract), list argv, never a shell
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from eyenet.stealer.extractor import ulpextract_path
from eyenet.telemetry.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Iterator

    from eyenet.stealer.clickhouse import ClickHouseCredsSink

_log = get_logger()
_ULPEXTRACT_COLUMNS = 8  # host,url,login,password,scheme,tld,source,ip_class

# Password-file names inside a stealer log tree (the ULP creds). Case-insensitive match
# on the basename; the tree is <channel>/<machine>/.../passwords.txt etc.
_PW_GLOBS = ("*password*.txt", "Passwords.txt")
# Rows per ClickHouse INSERT — bounds memory + keeps ReplacingMergeTree merges sane.
_INSERT_BATCH = 50_000
# unrar: -o+ overwrite, -inul suppress output, -p<pw> password (or -p- = none, never prompt).
_UNRAR = "unrar"


@dataclass(frozen=True, slots=True)
class ProcessResult:
    ok: bool
    creds_inserted: int
    password_used: str | None  # the candidate that opened it ("" = none/unencrypted)
    error: str | None = None


def _find_password_files(root: Path) -> list[Path]:
    out: list[Path] = []
    for pat in _PW_GLOBS:
        out.extend(root.rglob(pat))
    # dedup (a name can match two globs) + stable order
    return sorted(set(out))


def _extract(blob_path: Path, candidates: list[str], dest: Path) -> str | None:
    """Try each password candidate (then no-password) until the archive extracts.
    Returns the working password ("" = none), or None if nothing opened it."""
    attempts = [*candidates, ""]  # "" => -p- (unencrypted / watermark-only)
    for pw in attempts:
        dest.mkdir(parents=True, exist_ok=True)
        pw_arg = f"-p{pw}" if pw else "-p-"
        proc = subprocess.run(  # noqa: S603  # nosec B603 — fixed tool, list argv, no shell
            [_UNRAR, "x", "-o+", "-inul", pw_arg, str(blob_path), f"{dest}/"],
            capture_output=True,
            check=False,
            timeout=3600,
        )
        if proc.returncode == 0 and any(dest.iterdir()):
            return pw
        # wrong password / not this one — clear the partial tree and try the next
        shutil.rmtree(dest, ignore_errors=True)
    return None


def _ulpextract_rows(files: list[Path], source_label: str) -> Iterator[list[str]]:
    """Stream ulpextract's TSV output as 8-field rows. Subprocess, piped stdout."""
    binary = ulpextract_path()
    proc = subprocess.Popen(  # noqa: S603  # nosec B603 — fixed tool, list argv, no shell
        [binary, *[str(f) for f in files]],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    if proc.stdout is None:  # Popen(stdout=PIPE) guarantees a pipe; guard, don't assert
        raise RuntimeError("ulpextract subprocess has no stdout pipe")
    try:
        for line in proc.stdout:
            fields = line.rstrip("\n").split("\t")
            if len(fields) == _ULPEXTRACT_COLUMNS:
                # ulpextract's source column is the file path; override with a stable
                # provenance label (the channel/archive) for the corpus.
                fields[6] = source_label
                yield fields
    finally:
        proc.stdout.close()
        proc.wait()


def process_archive(
    *,
    blob_path: Path,
    password_candidates: list[str],
    work_root: Path,
    sink: ClickHouseCredsSink,
    source_label: str,
) -> ProcessResult:
    """Decrypt + extract the archive, ulpextract its password files, stream creds into
    ClickHouse. Cleans up the temp extraction tree. Synchronous — call via to_thread."""
    work_root.mkdir(parents=True, exist_ok=True)
    dest = Path(tempfile.mkdtemp(dir=work_root, prefix="ulp-"))
    try:
        pw = _extract(blob_path, password_candidates, dest)
        if pw is None:
            return ProcessResult(ok=False, creds_inserted=0, password_used=None,
                                 error="no password opened the archive")
        pw_files = _find_password_files(dest)
        if not pw_files:
            return ProcessResult(ok=True, creds_inserted=0, password_used=pw,
                                 error="no password files in archive")
        sink.ensure_schema()
        total = 0
        batch: list[list[str]] = []
        for row in _ulpextract_rows(pw_files, source_label):
            batch.append(row)
            if len(batch) >= _INSERT_BATCH:
                total += sink.insert_rows(batch)
                batch = []
        total += sink.insert_rows(batch)
        _log.info("stealer.archive_processed", creds=total, files=len(pw_files),
                  blob=blob_path.name)
        return ProcessResult(ok=True, creds_inserted=total, password_used=pw)
    finally:
        shutil.rmtree(dest, ignore_errors=True)  # never leave a 2 GB tree behind


__all__ = ["ProcessResult", "process_archive"]
