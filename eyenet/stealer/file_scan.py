"""Per-file heuristic classifier for the file_audit observability table (v1.2.6).

Walks a decrypted stealer-log work directory and emits one FileAudit per file.
Classification is best-effort from the file's first 4 KiB: enough to answer
"what filenames do we see that we are not parsing" without opening every file
to its end. All counts (banner / null-pw hits) are approximate (head-only) and
intentional; the point is "is this file worth writing a rule for", not an
exact rebuild of what ulpextract did.

No changes to the existing credential-extraction pipeline; this module is a
pure side channel. See development/STEALER_INFECTIONS_SCOPE.md for how the
audit table drives v1.3.0 rule-engine iteration.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

HeuristicKind = Literal[
    "empty",
    "binary",
    "text_unknown",
    "likely_creds",
    "likely_meta",
    "likely_json",
    "likely_cookie_tsv",
    "likely_screenshot",
    "likely_archive",
]

# A credential-shaped line: host-ish token, delimiter, user-ish, delimiter, pw-ish.
# Deliberately loose so it catches the common shapes (host:user:pass,
# https://host user:pass, email:pass, host|user|pass). Multi-line so we match
# ANY line in the head.
_CRED_LINE_RE = re.compile(rb"^[^\s:|,]+[:| ][^\s:|,]{1,80}[:|][^\s:|,]{1,80}", re.M)

# Metadata-ish key: value line (capitalized key, then colon, then value).
_META_KV_RE = re.compile(rb"^[A-Z][A-Za-z ]{2,30}:\s*\S", re.M)

# Same banner regex pattern as the ulpextract Go filter (keep in sync when
# v1.2.5's regex is tightened or replaced by rules in v1.3.0).
_BANNER_LOGIN_RE = re.compile(
    rb"(?i)^(tg|telegram|channel|our\s+channel|cloud\s+channel|subscribe|join)\b[\s:|-]|\st\.me/",
    re.M,
)

# Password placeholders a Chrome/Firefox export writes for an empty slot.
_NULL_PW_SET: frozenset[bytes] = frozenset(
    {b"", b"null", b"none", b"unknown", b"n/a", b"na", b"(null)", b"(none)", b"(empty)", b"nil"}
)

# Filenames we KNOW carry metadata (not credentials). Case-insensitive match.
_META_FILENAMES: frozenset[str] = frozenset(
    {
        "information.txt",
        "system.txt",
        "userinformation.txt",
        "userinformation",
        "informationfile.txt",
        "user information.txt",
        "details.txt",
        "environment.txt",
        "clipboard.txt",
        "processlist.txt",
        "installedsoftware.txt",
        "software.txt",
        "installedbrowsers.txt",
        "pc_info.json",
        "log_info.json",
        "domain_detect.txt",
        "domainsdetect.txt",
    }
)

_HEAD_BYTES = 4096
_SAMPLE_BYTES = 2048


@dataclass(frozen=True)
class FileAudit:
    """One row for the stealer.file_audit ClickHouse table."""

    rel_path: str
    filename: str
    size_bytes: int
    file_sha256: str
    heuristic_kind: HeuristicKind
    sample_head: str
    approx_banner_hits: int
    approx_null_pw_hits: int


_ASCII_PRINTABLE_MIN = 32  # ' '
_ASCII_PRINTABLE_MAX = 127  # DEL excluded
_PRINTABLE_TEXT_RATIO = 0.70  # anything below -> "binary"


def _classify(head: bytes, filename: str) -> HeuristicKind:  # noqa: PLR0911  # one return per file-kind
    if not head:
        return "empty"
    # Magic-byte checks first (cheapest).
    if head.startswith(b"\x89PNG") or head.startswith(b"\xff\xd8\xff") or head.startswith(b"GIF8"):
        return "likely_screenshot"
    if head.startswith((b"PK\x03\x04", b"Rar!", b"7z\xbc\xaf", b"\x1f\x8b")):
        return "likely_archive"
    # Printable-byte ratio (quick binary sniff).
    printable = sum(
        1 for c in head if _ASCII_PRINTABLE_MIN <= c < _ASCII_PRINTABLE_MAX or c in (9, 10, 13)
    )
    if printable / len(head) < _PRINTABLE_TEXT_RATIO:
        return "binary"
    # Known filename overrides pattern match (cheaper + more specific).
    fn_lower = filename.lower()
    if fn_lower in _META_FILENAMES:
        return "likely_meta"
    # JSON (object or array open, ignoring BOM).
    stripped = head.lstrip(b"\xef\xbb\xbf").lstrip()
    if stripped.startswith((b"{", b"[")):
        return "likely_json"
    # Cookies TSV: tab-separated, host\t... shape.
    if b"\t" in head and fn_lower.startswith("cookies"):
        return "likely_cookie_tsv"
    if _CRED_LINE_RE.search(head):
        return "likely_creds"
    if _META_KV_RE.search(head):
        return "likely_meta"
    return "text_unknown"


def _approx_null_pw(head: bytes) -> int:
    """Count head-only lines whose trailing ':'-delimited field is a null variant."""
    hits = 0
    for line in head.splitlines():
        if b":" not in line:
            continue
        pw = line.rsplit(b":", 1)[-1].strip().lower()
        if pw in _NULL_PW_SET:
            hits += 1
    return hits


def scan_file(path: Path, rel_path: str) -> FileAudit:
    """Classify one file by its head + hash the whole content. Raises OSError
    on an unreadable file; caller swallows (file may have vanished mid-walk)."""
    size = path.stat().st_size
    h = hashlib.sha256()
    with path.open("rb") as fh:
        head = fh.read(_HEAD_BYTES)
        h.update(head)
        while chunk := fh.read(65536):
            h.update(chunk)
    kind = _classify(head, path.name)
    sample = head[:_SAMPLE_BYTES].decode("utf-8", errors="replace") if head else ""
    banner_hits = len(_BANNER_LOGIN_RE.findall(head))
    null_hits = _approx_null_pw(head)
    return FileAudit(
        rel_path=rel_path,
        filename=path.name,
        size_bytes=size,
        file_sha256=h.hexdigest(),
        heuristic_kind=kind,
        sample_head=sample,
        approx_banner_hits=banner_hits,
        approx_null_pw_hits=null_hits,
    )


def walk_audit(root: Path) -> Iterator[FileAudit]:
    """Walk a per-archive work dir, yield one FileAudit per regular file.

    Symlinks and directories are skipped. Unreadable files (perms, race with
    cleanup) are silently skipped; this is a best-effort observability side
    channel, not a correctness-critical path."""
    for p in root.rglob("*"):
        if not p.is_file() or p.is_symlink():
            continue
        try:
            yield scan_file(p, str(p.relative_to(root)))
        except (OSError, ValueError):
            continue


__all__ = ["FileAudit", "HeuristicKind", "scan_file", "walk_audit"]
