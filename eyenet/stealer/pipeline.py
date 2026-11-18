# SPDX-License-Identifier: AGPL-3.0-or-later
"""ULP processing pipeline: encrypted archive blob to records in ClickHouse.

Pure of EYENET storage/bus. Takes a blob path + password candidates, runs
decrypt + gotractor rule extract + wallet-vault pass + file_audit +
classify, and returns a result. Synchronous (subprocess-heavy, CPU/IO
bound); the service runs it via ``asyncio.to_thread`` so it never blocks
the event loop. External tools run as SUBPROCESSES: process isolation
keeps a panic/OOM on an attacker-controlled archive out of the service's
address space.
"""

from __future__ import annotations

import json
import shutil
import subprocess  # nosec B404: fixed tool (unar), list argv, never a shell
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from eyenet.stealer.extractor import gotractor_path
from eyenet.telemetry.logging import get_logger

if TYPE_CHECKING:
    from eyenet.stealer.clickhouse import (
        ClickHouseRecordsSink,
        FileAuditSink,
    )
    from eyenet.stealer.gotractor_client import GotractorDaemon

_log = get_logger()

# Rows per ClickHouse INSERT. Bounds memory + keeps ReplacingMergeTree merges sane.
_INSERT_BATCH = 50_000
# ONE extractor for every container format a dump ships in — rar/rar5, 7z, zip, tar,
# tar.gz/.xz, gz. unar (The Unarchiver, Debian main) auto-detects the format and takes a
# password; unlike unrar it's not rar-only, and unlike 7z it opens the RAR5-encrypted-data
# variant these channels use. -q quiet, -f overwrite, -D no enclosing dir, -o dest.
_UNAR = "unar"


@dataclass(frozen=True, slots=True)
class ProcessResult:
    ok: bool
    password_used: str | None  # the candidate that opened it ("" = none/unencrypted)
    error: str | None = None
    records_inserted: int = 0  # gotractor rule-engine emit count
    gotractor_families: list[str] = field(default_factory=list)


_VICTIM_FOLDER_SEGMENT_IDX = 1


def _victim_folder_from_path(file_path: str) -> str:
    """Return the per-victim folder from a Khazan-style archive path.

    Archives nest as ``<channel_wrapper>/<victim>/<content>``, so the
    victim folder is path segment index 1. Matches the ClickHouse MV's
    ``splitByChar('/', file_path)[2]`` (1-indexed) in
    ``_VICTIM_PROFILES``. Returns "" when the file is at the archive
    root; victim_profiles MV filters those out.
    """
    segments = file_path.split("/", 2)
    if len(segments) <= _VICTIM_FOLDER_SEGMENT_IDX:
        return ""
    return segments[_VICTIM_FOLDER_SEGMENT_IDX]


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


def process_archive(
    *,
    blob_path: Path,
    password_candidates: list[str],
    work_root: Path,
    source_label: str,
    audit_sink: FileAuditSink | None = None,
    records_sink: ClickHouseRecordsSink | None = None,
    gotractor: GotractorDaemon | None = None,
) -> ProcessResult:
    """Decrypt the archive, run the gotractor rule engine + wallet-vault
    pass, stream records into ClickHouse, write file_audit + classify.
    Cleans up the temp extraction tree. Synchronous: call via to_thread.

    ``audit_sink`` is the file_audit observability side channel.
    ``records_sink`` is the gotractor landing sink for
    ``stealer.extracted_records``.
    """
    work_root.mkdir(parents=True, exist_ok=True)
    dest = Path(tempfile.mkdtemp(dir=work_root, prefix="ulp-"))
    try:
        pw = _extract(blob_path, password_candidates, dest)
        if pw is None:
            return ProcessResult(
                ok=False,
                password_used=None,
                error="no password opened the archive",
            )
        records = 0
        families: list[str] = []
        parse_errors: dict[str, tuple[str, str]] = {}
        if records_sink is not None and gotractor is not None:
            try:
                records, families, parse_errors = _gotractor_insert_daemon(
                    gotractor,
                    records_sink,
                    dest,
                    blob_path,
                    source_label,
                )
            except Exception as exc:
                # never fail pipeline on gotractor side
                _log.warning(
                    "stealer.gotractor_failed", error=str(exc), error_type=type(exc).__name__
                )
        # v1.3.2 wallet-vault extraction pass. Runs after the DSL records
        # pass because browser-wallet LevelDB vaults are a pre-DSL binary
        # extraction (goleveldb + idb_cmp1 comparer), not a regex rule.
        # Emits records in the same shape so they land in the same
        # extracted_records table with rule_id='wallet_vault_leveldb:*'
        # and family='<wallet_family>' (metamask / phantom / ronin / ...).
        if records_sink is not None:
            try:
                wallet_recs = _gotractor_extract_wallets(
                    records_sink,
                    dest,
                    blob_path,
                    source_label,
                )
                records += wallet_recs
            except Exception as exc:
                # wallet failures are never fatal
                _log.warning(
                    "stealer.wallet_extract_failed", error=str(exc), error_type=type(exc).__name__
                )
        if audit_sink is not None:
            _write_file_audit(audit_sink, dest, blob_path, parse_errors)
            # Classifier pass: now that file_audit + extracted_records are
            # populated for this archive, score every (archive, victim)
            # pair against the family catalog and persist the verdict.
            # Isolated like _write_file_audit: a classifier hiccup must
            # never propagate out to stealer_processor.done.
            _classify_archive_victims(blob_path.stem)
        return ProcessResult(
            ok=True,
            password_used=pw,
            records_inserted=records,
            gotractor_families=families,
        )
    finally:
        shutil.rmtree(dest, ignore_errors=True)  # never leave a 2 GB tree behind


def _gotractor_insert_daemon(
    daemon: GotractorDaemon,
    sink: ClickHouseRecordsSink,
    dest: Path,
    blob_path: Path,
    source_label: str,
) -> tuple[int, list[str], dict[str, tuple[str, str]]]:
    """Dispatch a 'run' command to the resident gotractor daemon, stream
    the record lines into ``stealer.extracted_records``. Returns
    ``(rows_inserted, family_tags, parse_errors)``.

    The Python process is the batcher; the Go daemon is the parser.
    Daemon mode: one resident subprocess for the service lifetime, no
    per-archive fork. Records stream through a thread-safe queue in
    GotractorDaemon.run().

    parse_errors maps rel_path -> (kind_code, error_msg). file_path=""
    is the archive-wide bucket (RunRules panic); _write_file_audit uses
    that as a fallback for every row that has no per-file attribution.
    """
    sink.ensure_schema()
    archive_sha = blob_path.stem  # <sha256>.bin
    stream, done_q = daemon.run(dest, source_label=source_label)
    total = 0
    families: list[str] = []
    parse_errors: dict[str, tuple[str, str]] = {}
    batch: list[list[object]] = []
    for msg in stream:
        if msg["_kind"] == "verdict":
            fam = msg.get("family")
            if fam:
                families.append(fam)
            continue
        if msg["_kind"] == "parse_error":
            parse_errors[msg.get("file_path", "")] = (
                msg.get("kind_code", "panic"),
                msg.get("error", ""),
            )
            _log.warning(
                "stealer.gotractor_parse_error",
                archive=archive_sha,
                rule_id=msg.get("rule_id") or "",
                file_path=msg.get("file_path") or "<archive-wide>",
                kind_code=msg.get("kind_code") or "panic",
                error=msg.get("error") or "",
            )
            continue
        # Record branch: derive per-victim folder from file_path segment [1] (second
        # path segment under the archive root, matching the Khazan wrapper
        # structure <channel_wrapper>/<victim>/<content>). Empty string if
        # the file is at the archive root; victim_profiles MV filters those
        # out. See eyenet/stealer/clickhouse.py _VICTIM_PROFILES for the
        # matching derivation at the MV level.
        file_path = msg.get("file_path", "")
        victim_folder = _victim_folder_from_path(file_path)
        batch.append(
            [
                archive_sha,
                source_label,
                victim_folder,
                file_path,
                msg.get("rule_id", ""),
                msg.get("family", ""),
                {k: str(v) for k, v in (msg.get("fields") or {}).items()},
            ]
        )
        if len(batch) >= _INSERT_BATCH:
            total += sink.insert_rows(batch)
            batch = []
    total += sink.insert_rows(batch)
    try:
        done = done_q.get(timeout=5.0)
        _log.info(
            "stealer.gotractor_run",
            archive=archive_sha,
            records=total,
            families=families,
            wall_ms=done.wall_ms,
            rules_fired=done.rules_fired,
        )
    except Exception:
        _log.info("stealer.gotractor_run", archive=archive_sha, records=total, families=families)
    return total, families, parse_errors


def _gotractor_extract_wallets(
    sink: ClickHouseRecordsSink,
    dest: Path,
    blob_path: Path,
    source_label: str,
) -> int:
    """Run ``gotractor --mode extract-wallets --input <dest>``, parse the
    one-record-per-line JSON output, and insert into the same
    ``stealer.extracted_records`` table as DSL records.

    Returns the number of vault records inserted.

    Not routed through the resident daemon because wallet extraction
    is a read-only, short-lived binary scan: no catalog, no watchers,
    no reload loop. A one-shot subprocess per archive is cleaner than
    extending the daemon protocol for a one-off mode.
    """
    archive_sha = blob_path.stem
    try:
        proc = subprocess.run(  # noqa: S603  # nosec B603
            [gotractor_path(), "--mode", "extract-wallets", "--input", str(dest)],
            capture_output=True,
            check=False,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        _log.warning("stealer.wallet_extract_timeout", archive=archive_sha)
        return 0
    if proc.returncode != 0:
        _log.warning(
            "stealer.wallet_extract_rc",
            archive=archive_sha,
            rc=proc.returncode,
            stderr=proc.stderr[:400],
        )
        return 0
    batch: list[list[object]] = []
    for raw_line in proc.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        # Derive per-victim folder from file_path segment [1] as in the
        # DSL records path above. Wallet extractor uses the LevelDB dir
        # as file_path which already carries the full path under the
        # archive root, so the same split produces the right victim.
        file_path = msg.get("file_path", "")
        victim_folder = _victim_folder_from_path(file_path)
        batch.append(
            [
                archive_sha,
                source_label,
                victim_folder,
                file_path,
                msg.get("rule_id", ""),
                msg.get("family", ""),
                {k: str(v) for k, v in (msg.get("fields") or {}).items()},
            ]
        )
    total = sink.insert_rows(batch) if batch else 0
    _log.info(
        "stealer.wallet_extract_run", archive=archive_sha, records=total, stderr=proc.stderr[:200]
    )
    return total


def _write_file_audit(
    audit_sink: FileAuditSink,
    dest: Path,
    blob_path: Path,
    parse_errors: dict[str, tuple[str, str]] | None = None,
) -> None:
    """Walk the decrypted work dir, scan every file, write rows to file_audit.

    Failures land as a WARN log, never raised: an audit-side DB hiccup must
    not propagate out to stealer_processor.done. ``archive_sha256`` is taken
    from the blob's filename (``<sha256>.bin``) so audit rows join back to the
    attachment row in PG by sha.

    ``parse_errors`` is the per-file gotractor crash map from the daemon
    stream: {rel_path: (kind_code, error_msg)}. The empty-string key is the
    archive-wide fallback (RunRules panic) applied to every row with no
    per-file attribution.

    ``extractor_touched`` is universally 1 now that ulpextract (which
    touched only password files) is gone and gotractor runs over the
    entire tree. The column is kept so historical queries still work;
    its semantics are "we scanned this file" not "we parsed records
    out of it" (the parsed signal lives in extracted_records)."""
    try:
        from eyenet.stealer.file_scan import walk_audit  # noqa: PLC0415

        audit_sink.ensure_schema()
        archive_sha = blob_path.stem  # <sha256>.bin -> <sha256>
        errs = parse_errors or {}
        archive_err = errs.get("", ("", ""))
        batch: list[list[object]] = []
        count = 0
        for a in walk_audit(dest):
            err_code, err_detail = errs.get(a.rel_path, archive_err)
            batch.append(
                [
                    archive_sha,
                    a.rel_path,
                    a.filename,
                    a.size_bytes,
                    a.file_sha256,
                    a.heuristic_kind,
                    1,  # extractor_touched: gotractor scans every file
                    a.approx_banner_hits,
                    a.approx_null_pw_hits,
                    a.sample_head,
                    err_code,
                    err_detail,
                ]
            )
            if len(batch) >= _INSERT_BATCH:
                count += audit_sink.insert_rows(batch)
                batch = []
        count += audit_sink.insert_rows(batch)
        _log.info("stealer.file_audit_written", archive=archive_sha, rows=count)
    except Exception as exc:
        # audit side channel; never fail the pipeline
        _log.warning("stealer.file_audit_failed", error=str(exc), error_type=type(exc).__name__)


def _classify_archive_victims(archive_sha: str) -> None:
    """Classify every victim under an archive and persist the verdicts.

    Called after _write_file_audit so the classifier reads a populated
    file_audit + extracted_records. Failures are swallowed with a WARN
    log; a verdict-side DB hiccup must not break the attachment done
    path. Catalog load + CH client are one-shots per archive (cheap,
    archives arrive seconds apart at most)."""
    try:
        from eyenet.stealer.classifier import classify  # noqa: PLC0415
        from eyenet.stealer.classifier_io import (  # noqa: PLC0415
            collect_evidence_sync,
            write_verdict_sync,
        )
        from eyenet.stealer.clickhouse import (  # noqa: PLC0415
            clickhouse_db,
            get_clickhouse_client,
        )

        client = get_clickhouse_client()
        db = clickhouse_db()
        rows = client.query(
            "SELECT DISTINCT victim_folder "  # noqa: S608  # nosec B608
            f"FROM {db}.file_audit FINAL "
            "WHERE archive_sha256 = %(sha)s "
            "  AND victim_folder != ''",
            parameters={"sha": archive_sha},
        ).result_rows
        count = 0
        for (vf,) in rows:
            ev = collect_evidence_sync(client, archive_sha, str(vf))
            result = classify(ev)
            write_verdict_sync(client, archive_sha, str(vf), result)
            count += 1
        _log.info("stealer.classifier_written", archive=archive_sha, victims=count)
    except Exception as exc:
        _log.warning("stealer.classifier_failed", error=str(exc), error_type=type(exc).__name__)


__all__ = ["ProcessResult", "process_archive"]
