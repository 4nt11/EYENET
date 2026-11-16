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

    from eyenet.stealer.clickhouse import ClickHouseCredsSink, FileAuditSink

_log = get_logger()
_ULPEXTRACT_COLUMNS = 9  # host,url,login,password,scheme,tld,source,ip_class,source_file

# Password-file glob inside a stealer log tree (the ULP creds). Matched case-INSENSITIVE
# (3.12 rglob) because dumps mix casings: passwords.txt, Passwords.txt, All Passwords.txt,
# <soft>_passwords.txt, passwords_unique.txt. The tree is <channel>/<machine>/.../*.txt.
_PW_GLOB = "*password*.txt"
# Rows per ClickHouse INSERT — bounds memory + keeps ReplacingMergeTree merges sane.
_INSERT_BATCH = 50_000
# ONE extractor for every container format a dump ships in — rar/rar5, 7z, zip, tar,
# tar.gz/.xz, gz. unar (The Unarchiver, Debian main) auto-detects the format and takes a
# password; unlike unrar it's not rar-only, and unlike 7z it opens the RAR5-encrypted-data
# variant these channels use. -q quiet, -f overwrite, -D no enclosing dir, -o dest.
_UNAR = "unar"


@dataclass(frozen=True, slots=True)
class ProcessResult:
    ok: bool
    creds_inserted: int
    password_used: str | None  # the candidate that opened it ("" = none/unencrypted)
    error: str | None = None


def _find_password_files(root: Path) -> list[Path]:
    # case_sensitive=False (Python 3.12) so one glob catches every casing.
    return sorted(root.rglob(_PW_GLOB, case_sensitive=False))


def _any_nonempty_file(root: Path) -> bool:
    """True if any extracted file has content. The success signal for a password:
    a WRONG password on an encrypted archive still writes the (unencrypted) names as
    0-byte stubs, so file COUNT is a false positive — only decrypted data is nonempty."""
    return any(f.is_file() and f.stat().st_size > 0 for f in root.rglob("*"))


def _extract(blob_path: Path, candidates: list[str], dest: Path) -> str | None:
    """Try each password candidate (then no-password) until the archive extracts with
    real content. Returns the working password ("" = none), or None if nothing opened it.
    Candidates are ordered best-first, so the usual case extracts exactly once."""
    attempts = [*candidates, ""]  # "" => no -p (unencrypted / watermark-only)
    for pw in attempts:
        dest.mkdir(parents=True, exist_ok=True)
        cmd = [_UNAR, "-q", "-f", "-D", "-o", str(dest)]
        if pw:
            cmd += ["-p", pw]
        cmd.append(str(blob_path))
        subprocess.run(  # noqa: S603  # nosec B603 — fixed tool, list argv, no shell
            cmd,
            capture_output=True,
            check=False,
            timeout=3600,
            stdin=subprocess.DEVNULL,  # never block on a password prompt
        )
        # unar returns 0 even when every file "Failed! (wrong password)", so the real
        # signal is decrypted content on disk, not the exit code.
        if _any_nonempty_file(dest):
            return pw
        shutil.rmtree(dest, ignore_errors=True)  # wrong password — clear stubs, try next
    return None


def _ulpextract_rows(files: list[Path], source_label: str) -> Iterator[list[str]]:
    """Stream ulpextract's TSV output as 8-field rows. Subprocess, piped stdout."""
    binary = ulpextract_path()
    proc = subprocess.Popen(  # noqa: S603  # nosec B603 — fixed tool, list argv, no shell
        [binary, *[str(f) for f in files]],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        # Stealer archives frequently carry legacy Windows codepage bytes
        # (cp1252 or cp1251 Cyrillic) in passwords and paths scooped from
        # non-English user machines. Strict decode would raise
        # UnicodeDecodeError on the first such byte and kill the whole
        # archive; "replace" is lossy for that single byte but keeps the
        # surrounding credential intact. Dedup identity is (host, login,
        # password), so a single '?' in a password does not meaningfully
        # change what the row collapses onto.
        errors="replace",
    )
    if proc.stdout is None:  # Popen(stdout=PIPE) guarantees a pipe; guard, don't assert
        raise RuntimeError("ulpextract subprocess has no stdout pipe")
    try:
        for line in proc.stdout:
            fields = line.rstrip("\n").split("\t")
            if len(fields) == _ULPEXTRACT_COLUMNS:
                # Columns 6 and 8 are the two levels of provenance:
                #   fields[6] "source": the dump bucket (archive basename);
                #   fields[8] "source_file": the per-record file path inside
                #     the decrypted archive (``.../<victim-folder>/passwords.txt``)
                # We overwrite column 6 with ``source_label`` (the stealer
                # channel + archive marker) so corpus queries have a stable
                # outside-the-archive identity; we leave column 8 as-is so
                # operators can trace a bad row back to the exact inner file
                # that produced it (prerequisite for the v1.3.0 infection
                # metadata join, and the only way to debug a future extractor
                # bug without re-running ulpextract by hand).
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
    audit_sink: FileAuditSink | None = None,
) -> ProcessResult:
    """Decrypt + extract the archive, ulpextract its password files, stream creds into
    ClickHouse. Cleans up the temp extraction tree. Synchronous: call via to_thread.

    ``audit_sink`` is the v1.2.6 side channel for the file_audit observability
    table. When present, every file in the decrypted work dir is classified +
    sampled into a row AFTER the credential extraction runs (so an audit sink
    misconfig cannot break the primary creds path). None keeps the pre-v1.2.6
    behaviour (no audit rows written)."""
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
        if audit_sink is not None:
            _write_file_audit(audit_sink, dest, blob_path, pw_files)
        return ProcessResult(ok=True, creds_inserted=total, password_used=pw)
    finally:
        shutil.rmtree(dest, ignore_errors=True)  # never leave a 2 GB tree behind


def _write_file_audit(
    audit_sink: FileAuditSink, dest: Path, blob_path: Path, pw_files: list[Path]
) -> None:
    """Walk the decrypted work dir, scan every file, write rows to file_audit.

    Failures land as a WARN log, never raised: an audit-side DB hiccup must
    not propagate out to stealer_processor.done. ``archive_sha256`` is taken
    from the blob's filename (``<sha256>.bin``) so audit rows join back to the
    attachment row in PG by sha."""
    try:
        from eyenet.stealer.file_scan import walk_audit  # noqa: PLC0415

        audit_sink.ensure_schema()
        pw_rel = {str(p.relative_to(dest)) for p in pw_files}
        archive_sha = blob_path.stem  # <sha256>.bin -> <sha256>
        batch: list[list[object]] = []
        count = 0
        for a in walk_audit(dest):
            batch.append(
                [
                    archive_sha,
                    a.rel_path,
                    a.filename,
                    a.size_bytes,
                    a.file_sha256,
                    a.heuristic_kind,
                    1 if a.rel_path in pw_rel else 0,
                    0,  # rows_emitted: v1.2.6 cannot count per-file yet; v1.3.0 fills it
                    a.approx_banner_hits,
                    a.approx_null_pw_hits,
                    a.sample_head,
                ]
            )
            if len(batch) >= _INSERT_BATCH:
                count += audit_sink.insert_rows(batch)
                batch = []
        count += audit_sink.insert_rows(batch)
        _log.info("stealer.file_audit_written", archive=archive_sha, rows=count)
    except Exception as exc:  # noqa: BLE001 - audit side channel; never fail the pipeline
        _log.warning("stealer.file_audit_failed", error=str(exc), error_type=type(exc).__name__)


__all__ = ["ProcessResult", "process_archive"]
