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
import os
import shutil
import subprocess  # nosec B404: fixed tools (7zz/unrar/unar), list argv, never a shell
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

# Rows per ClickHouse INSERT. Used by the legacy sink.insert_rows path
# (backfill CLIs, reclassify dumps). The main pipeline no longer batches
# through Python since v1.4.0: gotractor writes to CH directly.
_INSERT_BATCH = 50_000
# Three-tier dispatch: RAR goes to unrar (RAR5-native, ~25x faster than unar on
# prod-sized 2GB dumps: measured 10.8s vs 272s), non-RAR to 7zz (multithreaded
# AES + SIMD CRC for 7z/zip/tar/gz/xz), unar is the last-resort fallback for
# the archives that both tools choke on. unar is single-threaded XADMaster;
# keeping it on the cold path. EYENET_STEALER_EXTRACT_TOOL=unar|7zz|unrar
# forces one tool (operator kill switch); =auto is the default dispatch.
_RAR_MAGIC = b"Rar!\x1a\x07"  # covers RAR4 (\x00 trailer) and RAR5 (\x01 trailer)
_TOOL_OVERRIDE = os.environ.get("EYENET_STEALER_EXTRACT_TOOL", "auto")
_FALLBACK_DISABLED = os.environ.get("EYENET_STEALER_EXTRACT_FALLBACK", "") == "disable"


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


def _pick_tool(blob_path: Path) -> str:
    """Pick extractor from the override env var, or the first 8 magic bytes:
    RAR to unrar, everything else to 7zz. Override forces one tool."""
    if _TOOL_OVERRIDE in {"unar", "7zz", "unrar"}:
        return _TOOL_OVERRIDE
    try:
        with blob_path.open("rb") as f:
            head = f.read(8)
    except OSError:
        return "7zz"
    if head.startswith(_RAR_MAGIC):
        return "unrar"
    return "7zz"


def _extract_cmd(tool: str, blob: Path, dest: Path, pw: str) -> list[str]:
    """Build the argv for one tool invocation. Password goes inline (never as
    stdin) so a wrong-password archive fails fast instead of hanging on a
    prompt."""
    if tool == "7zz":
        # -bso0/-bse0 silence stdout+stderr, -p<pw> inline (empty = no password),
        # -y assume yes, -mmt=on multithreaded. 7zz treats an empty -p as "no
        # password" and does not prompt.
        return [
            "7zz",
            "x",
            "-y",
            "-bso0",
            "-bse0",
            f"-o{dest}",
            f"-p{pw}",
            "-mmt=on",
            str(blob),
        ]
    if tool == "unrar":
        # -inul suppresses all messages, -o+ overwrite without prompting,
        # -p<pw> inline (-p- = no password, suppress prompt). Trailing slash
        # on dest tells unrar it's a directory.
        pw_arg = f"-p{pw}" if pw else "-p-"
        return ["unrar", "x", "-o+", "-inul", pw_arg, str(blob), f"{dest}/"]
    # unar fallback: -q quiet, -f overwrite, -D no enclosing dir, -o dest.
    cmd = ["unar", "-q", "-f", "-D", "-o", str(dest)]
    if pw:
        cmd += ["-p", pw]
    cmd.append(str(blob))
    return cmd


def _try_tool(tool: str, blob_path: Path, dest: Path, pw: str) -> bool:
    """Run one tool with one password candidate. Returns True iff real decrypted
    content landed on disk (not just 0-byte stubs from a wrong password)."""
    dest.mkdir(parents=True, exist_ok=True)
    subprocess.run(  # noqa: S603  # nosec B603 - fixed tool, list argv, no shell
        _extract_cmd(tool, blob_path, dest, pw),
        capture_output=True,
        check=False,
        timeout=3600,
        stdin=subprocess.DEVNULL,
    )
    if _any_nonempty_file(dest):
        return True
    shutil.rmtree(dest, ignore_errors=True)
    return False


def _extract(blob_path: Path, candidates: list[str], dest: Path) -> tuple[str, str] | None:
    """Try each password candidate (then no-password) until the archive extracts
    with real content. Returns (password, tool) on success, or None if nothing
    opened it. Candidates are ordered best-first, so the usual case extracts
    exactly once."""
    primary = _pick_tool(blob_path)
    attempts = [*candidates, ""]  # "" => no password (unencrypted / watermark-only)
    for pw in attempts:
        if _try_tool(primary, blob_path, dest, pw):
            return pw, primary
    # Fallback: 7zz/unrar failed on every password but the archive may be a
    # RAR5-encrypted-data variant only XADMaster handles. unar takes one shot
    # with the best candidate before we declare failure.
    if primary != "unar" and not _FALLBACK_DISABLED:
        for pw in attempts:
            if _try_tool("unar", blob_path, dest, pw):
                _log.info(
                    "stealer.extract_fallback_unar",
                    blob=blob_path.name,
                    primary=primary,
                )
                return pw, "unar"
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
        extracted = _extract(blob_path, password_candidates, dest)
        if extracted is None:
            return ProcessResult(
                ok=False,
                password_used=None,
                error="no password opened the archive",
            )
        pw, tool = extracted
        _log.debug("stealer.extract_ok", blob=blob_path.name, tool=tool)
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
    stream, done_q = daemon.run(
        dest,
        source_label=source_label,
        archive_sha256=archive_sha,
    )
    families: list[str] = []
    parse_errors: dict[str, tuple[str, str]] = {}
    # v1.4.0: gotractor with EYENET_GOTRACTOR_CH_DSN writes records
    # DIRECTLY to ClickHouse. The stream iterator yields only
    # verdict / parse_error / truncated metadata here; Python never
    # sees the record payload, never buffers it, never inserts it.
    # Dropped: _INSERT_BATCH batching, _PENDING_BATCH_CAP semaphore,
    # the ThreadPoolExecutor, sink.insert_rows calls.
    #
    # When the daemon runs WITHOUT a DSN (dev workflows, backfill CLIs
    # that spin up a fresh daemon per invocation), it falls back to the
    # legacy stdout-record stream. We still drop those records on the
    # floor here -- the recorded-to-CH operator contract is "daemon
    # with DSN == prod path, daemon without DSN == dev/test path". The
    # dropped-record case shows up as an unexpected_record warning so
    # it never slips past silently.
    for msg in stream:
        kind = msg["_kind"]
        if kind == "verdict":
            fam = msg.get("family")
            if fam:
                families.append(fam)
            continue
        if kind == "parse_error":
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
        if kind == "record":
            # Daemon without DSN still emits record lines. Ignore them,
            # loud so a misconfigured deploy is caught early.
            _log.warning(
                "stealer.gotractor_unexpected_record",
                archive=archive_sha,
                rule_id=msg.get("rule_id") or "",
                hint="daemon emitted a record line - set EYENET_GOTRACTOR_CH_DSN",
            )
            continue
        # Other kinds (truncated etc.) already logged by the client.
    try:
        done = done_q.get(timeout=10.0)
        total = done.records
        _log.info(
            "stealer.gotractor_run",
            archive=archive_sha,
            records=total,
            families=families,
            wall_ms=done.wall_ms,
            rules_fired=done.rules_fired,
        )
    except Exception:
        total = 0
        _log.info(
            "stealer.gotractor_run",
            archive=archive_sha,
            records=total,
            families=families,
            warn="no run_done received before timeout",
        )
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
        # v1.3.5: dropped FINAL; see classifier_io.py.
        rows = client.query(
            "SELECT DISTINCT victim_folder "  # noqa: S608  # nosec B608
            f"FROM {db}.file_audit "
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
