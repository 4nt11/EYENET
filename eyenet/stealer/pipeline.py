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

import json
import os
import shutil
import subprocess  # nosec B404: fixed tools (unrar/ulpextract/gotractor), list argv, never a shell
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from eyenet.stealer.extractor import gotractor_path, ulpextract_path
from eyenet.telemetry.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Iterator

    from eyenet.stealer.clickhouse import (
        ClickHouseCredsSink,
        ClickHouseRecordsSink,
        FileAuditSink,
    )

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
    # v1.3.1: gotractor side ran in parallel with ulpextract; count tracks how
    # many records the DSL engine emitted from this same archive. During the
    # cutover we dual-write and reconcile; once gotractor is authoritative the
    # ulpextract count stays at 0.
    records_inserted: int = 0
    gotractor_families: list[str] = field(default_factory=list)


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
    records_sink: ClickHouseRecordsSink | None = None,
    rules_dir: Path | str | None = None,
    families_dir: Path | str | None = None,
) -> ProcessResult:
    """Decrypt + extract the archive, run BOTH extractors (ulpextract for the
    legacy TSV creds table, gotractor for the new rule-driven records table),
    stream into ClickHouse. Cleans up the temp extraction tree. Synchronous:
    call via to_thread.

    ``audit_sink`` is the v1.2.6 side channel for the file_audit observability
    table.

    ``records_sink`` (v1.3.1) is the gotractor landing sink for the new
    ``stealer.extracted_records`` table. When present, gotractor runs after
    the ulpextract pass and streams one record per rule match into the
    Map(String, String) fields column. When None, the gotractor leg is
    skipped entirely, preserving pre-cutover behaviour.
    """
    work_root.mkdir(parents=True, exist_ok=True)
    dest = Path(tempfile.mkdtemp(dir=work_root, prefix="ulp-"))
    try:
        pw = _extract(blob_path, password_candidates, dest)
        if pw is None:
            return ProcessResult(ok=False, creds_inserted=0, password_used=None,
                                 error="no password opened the archive")
        pw_files = _find_password_files(dest)
        total = 0
        if pw_files:
            sink.ensure_schema()
            batch: list[list[str]] = []
            for row in _ulpextract_rows(pw_files, source_label):
                batch.append(row)
                if len(batch) >= _INSERT_BATCH:
                    total += sink.insert_rows(batch)
                    batch = []
            total += sink.insert_rows(batch)
            _log.info("stealer.archive_processed", creds=total, files=len(pw_files),
                      blob=blob_path.name)
        # v1.3.1 gotractor dual-write. Runs on the ENTIRE extracted tree
        # (not just pw files) because the DSL rules fire on cookies,
        # autofills, bookmarks, credentials_windows, json_v2 metadata,
        # etc., not only passwords.txt.
        records = 0
        families: list[str] = []
        if records_sink is not None:
            try:
                records, families = _gotractor_insert(
                    records_sink, dest, blob_path, source_label, rules_dir, families_dir,
                )
            except Exception as exc:  # noqa: BLE001 - never fail pipeline on gotractor side
                _log.warning("stealer.gotractor_failed", error=str(exc),
                             error_type=type(exc).__name__)
        if audit_sink is not None:
            _write_file_audit(audit_sink, dest, blob_path, pw_files)
        if not pw_files and records == 0:
            return ProcessResult(ok=True, creds_inserted=0, password_used=pw,
                                 error="no password files in archive",
                                 records_inserted=0, gotractor_families=[])
        return ProcessResult(
            ok=True, creds_inserted=total, password_used=pw,
            records_inserted=records, gotractor_families=families,
        )
    finally:
        shutil.rmtree(dest, ignore_errors=True)  # never leave a 2 GB tree behind


def _gotractor_insert(
    sink: ClickHouseRecordsSink,
    dest: Path,
    blob_path: Path,
    source_label: str,
    rules_dir: Path | str | None,
    families_dir: Path | str | None,
) -> tuple[int, list[str]]:
    """Spawn gotractor on the extracted tree, stream JSON records into
    ``stealer.extracted_records``. Returns ``(rows_inserted, family_tags)``.

    The Python process is the batcher; the Go process is the parser.
    Records-mode output on gotractor's stdout is one JSON object per line
    of three kinds: ``verdict`` (container tag), ``record`` (the data),
    ``truncated`` (soft limit notice, logged). We batch every record
    into an INSERT every ``_INSERT_BATCH`` rows."""
    sink.ensure_schema()
    archive_sha = blob_path.stem  # <sha256>.bin
    victim_folder = dest.name
    env = {**os.environ}
    if rules_dir:
        env["EYENET_STEALER_RULES_DIR"] = str(rules_dir)
    if families_dir:
        env["EYENET_STEALER_FAMILIES_DIR"] = str(families_dir)
    if not env.get("EYENET_STEALER_RULES_DIR") or not env.get("EYENET_STEALER_FAMILIES_DIR"):
        raise RuntimeError(
            "gotractor needs EYENET_STEALER_RULES_DIR + EYENET_STEALER_FAMILIES_DIR "
            "(or pass rules_dir / families_dir to process_archive)"
        )
    proc = subprocess.Popen(  # noqa: S603  # nosec B603 - fixed tool, list argv, no shell
        [gotractor_path(), "--mode=records", "--input", str(dest)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    assert proc.stdout is not None  # noqa: S101 - documented API of Popen(stdout=PIPE)
    total = 0
    families: list[str] = []
    batch: list[list[object]] = []
    try:
        for line in proc.stdout:
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = d.get("kind")
            if kind == "verdict":
                fam = d.get("family")
                if fam:
                    families.append(fam)
            elif kind == "record":
                batch.append(
                    [
                        archive_sha,
                        source_label,
                        victim_folder,
                        d.get("file_path", ""),
                        d.get("rule_id", ""),
                        d.get("family", ""),
                        {k: str(v) for k, v in (d.get("fields") or {}).items()},
                    ]
                )
                if len(batch) >= _INSERT_BATCH:
                    total += sink.insert_rows(batch)
                    batch = []
            elif kind == "truncated":
                _log.warning(
                    "stealer.gotractor_truncated",
                    rule_id=d.get("rule_id"), file_path=d.get("file_path"),
                    emitted=d.get("emitted"), total_seen=d.get("total_seen"),
                )
        total += sink.insert_rows(batch)
    finally:
        proc.stdout.close()
        proc.wait()
    _log.info("stealer.gotractor_run", archive=archive_sha, records=total,
              families=families)
    return total, families


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
