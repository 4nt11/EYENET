# SPDX-License-Identifier: AGPL-3.0-or-later
"""Python client for the gotractor daemon.

Owns ONE long-lived gotractor subprocess per service. Serialises commands
over stdin, reads newline-delimited JSON off stdout, correlates responses
to requests via ``req_id``. Fully blocking (one in-flight run at a time);
the service runs it via ``asyncio.to_thread`` so it doesn't block the
event loop. Thread-safe only via its own internal lock.

Lifecycle: ``GotractorDaemon.start()`` spawns the process + loader
thread, ``.run(folder)`` returns an iterator of extracted records,
``.reload()`` forces a catalog refresh, ``.stats()`` reads counters,
``.close()`` sends a shutdown command and waits.
"""

from __future__ import annotations

import json
import os
import subprocess  # nosec B404
import threading
import uuid
from dataclasses import dataclass
from queue import Queue
from typing import TYPE_CHECKING, Any

from eyenet.stealer.extractor import gotractor_path
from eyenet.telemetry.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_log = get_logger()


@dataclass(frozen=True, slots=True)
class RunDone:
    """Terminal response for a 'run' command. ``rules_fired`` is a
    per-rule emitted-count dict; ``records`` is the total across all
    content rules; ``wall_ms`` is gotractor's own wall-clock for the
    archive (pure extraction, no CH insert time)."""

    records: int
    wall_ms: int
    rules_fired: dict[str, int]


class GotractorError(RuntimeError):
    """Raised when the daemon returns an 'error' line for a request."""


class GotractorDaemon:
    """Thin resident-subprocess client.

    The daemon returns records as a stream (one JSON line per record)
    so Python can batch into ClickHouse without ever buffering the full
    result in memory. ``run()`` returns an iterator that yields each
    record's ``fields`` dict as it arrives; the iterator terminates at
    the ``run_done`` line (whose payload is attached to the iterator).
    """

    def __init__(
        self,
        *,
        rules_dir: Path | str,
        families_dir: Path | str,
        metrics_port: int | None = None,
        bulk_limit: int = 100_000,
    ) -> None:
        self._rules_dir = str(rules_dir)
        self._families_dir = str(families_dir)
        self._metrics_port = metrics_port
        self._bulk_limit = bulk_limit
        self._proc: subprocess.Popen[str] | None = None
        self._reader_thread: threading.Thread | None = None
        # Per-req_id queue of JSON messages the reader thread delivers.
        self._queues: dict[str, Queue[dict[str, Any]]] = {}
        # Protects the queues dict + stdin write (one in-flight at a time
        # is assumed; pipelining would need per-req locking).
        self._mu = threading.Lock()
        self._closed = False

    def start(self) -> None:
        if self._proc is not None:
            return
        cmd = [
            gotractor_path(),
            "--mode=daemon",
            "--rules-dir",
            self._rules_dir,
            "--families-dir",
            self._families_dir,
            "--limit",
            str(self._bulk_limit),
        ]
        if self._metrics_port:
            cmd += ["--metrics-port", str(self._metrics_port)]
        env = {
            **os.environ,
            "EYENET_STEALER_RULES_DIR": self._rules_dir,
            "EYENET_STEALER_FAMILIES_DIR": self._families_dir,
        }
        self._proc = subprocess.Popen(  # noqa: S603  # nosec B603
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            bufsize=1,  # line-buffered
        )
        # Reader thread demultiplexes stdout by req_id into per-request queues.
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()
        _log.info(
            "gotractor.daemon.started", rules_dir=self._rules_dir, metrics_port=self._metrics_port
        )

    def _reader_loop(self) -> None:
        assert self._proc is not None  # noqa: S101
        assert self._proc.stdout is not None  # noqa: S101
        try:
            for raw_line in self._proc.stdout:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    _log.warning("gotractor.daemon.bad_line", line=line[:200])
                    continue
                rid = msg.get("req_id")
                with self._mu:
                    q = self._queues.get(rid) if rid else None
                if q is not None:
                    q.put(msg)
                # Unsolicited (fs-reload, plain error): log, do nothing.
                elif msg.get("kind") == "reloaded":
                    _log.info(
                        "gotractor.daemon.catalog_reloaded",
                        rules=msg.get("rules"),
                        families=msg.get("families"),
                        trigger=msg.get("trigger"),
                    )
                elif msg.get("kind") == "error":
                    _log.warning("gotractor.daemon.unsolicited_error", error=msg.get("error"))
        except Exception as exc:
            _log.warning("gotractor.daemon.reader_loop_crashed", error=str(exc))

    # ---- public ops ----

    def run(
        self,
        input_path: Path | str,
        *,
        source_label: str = "",
    ) -> tuple[Iterator[dict[str, Any]], Queue[RunDone]]:
        """Dispatch a 'run' command. Returns an iterator that yields each
        ``record`` line's ``fields`` dict as gotractor emits it, plus a
        one-shot queue that eventually gets the terminal ``RunDone``.
        Caller is responsible for consuming the iterator to completion
        (otherwise the reader thread will block on a full queue).
        """
        if self._proc is None:
            raise RuntimeError("GotractorDaemon.start() first")
        rid = uuid.uuid4().hex
        q: Queue[dict[str, Any]] = Queue()
        done_q: Queue[RunDone] = Queue(maxsize=1)
        with self._mu:
            self._queues[rid] = q
            assert self._proc.stdin is not None  # noqa: S101
            self._proc.stdin.write(
                json.dumps(
                    {
                        "cmd": "run",
                        "req_id": rid,
                        "input": str(input_path),
                        "source_label": source_label,
                    }
                )
                + "\n"
            )
            self._proc.stdin.flush()

        def _iter() -> Iterator[dict[str, Any]]:
            family: str | None = None
            try:
                while True:
                    msg = q.get()
                    kind = msg.get("kind")
                    if kind == "verdict":
                        family = msg.get("family")
                        # Yield the verdict as a sentinel first-record so
                        # the pipeline can tag the whole batch.
                        yield {
                            "_kind": "verdict",
                            "family": family,
                            "root": msg.get("root"),
                            "files": msg.get("files"),
                        }
                    elif kind == "record":
                        yield {
                            "_kind": "record",
                            "rule_id": msg.get("rule_id"),
                            "family": msg.get("family"),
                            "file_path": msg.get("file_path"),
                            "fields": msg.get("fields") or {},
                        }
                    elif kind == "parse_error":
                        # Per-file or archive-wide gotractor crash. The
                        # daemon's recover() caught a panic in BulkParse
                        # (file_path set) or RunRules (file_path="", one
                        # marker per archive run). Downstream writes
                        # parse_error cols onto the matching file_audit
                        # rows so the operator can find the files that
                        # make the extractor explode.
                        yield {
                            "_kind": "parse_error",
                            "rule_id": msg.get("rule_id") or "",
                            "file_path": msg.get("file_path") or "",
                            "error": str(msg.get("error") or "")[:400],
                            "kind_code": msg.get("kind_code") or "panic",
                        }
                    elif kind == "truncated":
                        _log.warning(
                            "gotractor.daemon.truncated",
                            rule_id=msg.get("rule_id"),
                            file_path=msg.get("file_path"),
                            emitted=msg.get("emitted"),
                            total_seen=msg.get("total_seen"),
                        )
                    elif kind == "run_done":
                        done_q.put(
                            RunDone(
                                records=msg.get("records", 0),
                                wall_ms=msg.get("wall_ms", 0),
                                rules_fired=msg.get("rules_fired") or {},
                            )
                        )
                        return
                    elif kind == "error":
                        raise GotractorError(str(msg.get("error")))
            finally:
                with self._mu:
                    self._queues.pop(rid, None)

        return _iter(), done_q

    def reload(self) -> dict[str, Any]:
        return self._request({"cmd": "reload"})

    def stats(self) -> dict[str, Any]:
        return self._request({"cmd": "stats"})

    def close(self) -> None:
        if self._closed or self._proc is None:
            return
        self._closed = True
        try:
            self._request({"cmd": "shutdown"}, timeout_s=5.0)
        except Exception as exc:
            _log.warning("gotractor.daemon.shutdown_failed", error=str(exc))
        try:
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._proc.kill()
        _log.info("gotractor.daemon.closed")

    # ---- impl helpers ----

    def _request(self, payload: dict[str, Any], *, timeout_s: float = 30.0) -> dict[str, Any]:
        if self._proc is None:
            raise RuntimeError("GotractorDaemon.start() first")
        rid = uuid.uuid4().hex
        q: Queue[dict[str, Any]] = Queue()
        with self._mu:
            self._queues[rid] = q
            assert self._proc.stdin is not None  # noqa: S101
            self._proc.stdin.write(json.dumps({**payload, "req_id": rid}) + "\n")
            self._proc.stdin.flush()
        try:
            msg = q.get(timeout=timeout_s)
        finally:
            with self._mu:
                self._queues.pop(rid, None)
        if msg.get("kind") == "error":
            raise GotractorError(str(msg.get("error")))
        return msg


__all__ = ["GotractorDaemon", "GotractorError", "RunDone"]
