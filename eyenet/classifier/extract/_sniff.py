"""Magic-byte file-type routing — content, never extension.

A ``.txt`` may be a PDF; a ``.docx`` may be a zip bomb. The classifier trusts
the *bytes*, not the name. This sniffer is deliberately minimal: it reads only
the leading signature and decides which jailed parser should handle the blob.
It never introspects a container (no ZIP central-directory walk, no XML parse) —
that is the in-jail parser's job, and keeping host-side parsing of untrusted
bytes near zero is the whole point of the sandbox.
"""

from __future__ import annotations

import enum


class DocKind(enum.Enum):
    """The parser class a blob routes to (decided from its leading bytes)."""

    PDF = "pdf"  # %PDF — pymupdf text layer
    ZIP_OOXML = "zip_ooxml"  # PK.. — python-docx (validates/rejects in-jail)
    IMAGE = "image"  # PNG/JPEG/TIFF/GIF/BMP/WEBP — Tesseract OCR
    TEXT = "text"  # decodes cleanly as text — stdlib decode
    RTF = "rtf"  # {\rtf — stdlib control-word stripper
    HTML = "html"  # <html / <!doctype html — stdlib html.parser
    UNKNOWN = "unknown"  # nothing matched — fail closed


# Leading-byte signatures, longest/most-specific intent first. Images share one
# kind (all route to Tesseract). RTF/PDF are exact prefixes.
_IMAGE_SIGNATURES: tuple[bytes, ...] = (
    b"\x89PNG\r\n\x1a\n",  # PNG
    b"\xff\xd8\xff",  # JPEG
    b"II*\x00",  # TIFF little-endian
    b"MM\x00*",  # TIFF big-endian
    b"GIF87a",
    b"GIF89a",
    b"BM",  # BMP
)

_HTML_MARKERS: tuple[bytes, ...] = (
    b"<!doctype html",
    b"<html",
    b"<head",
    b"<?xml",  # an XML/XHTML document — treat as HTML for text extraction
)

# Exact leading-byte prefixes that map straight to a kind (most specific first).
_PREFIX_KINDS: tuple[tuple[bytes, DocKind], ...] = (
    (b"%PDF", DocKind.PDF),
    (b"PK\x03\x04", DocKind.ZIP_OOXML),
    (b"{\\rtf", DocKind.RTF),
)

_WEBP_HEADER_LEN = 12  # RIFF(4) + size(4) + WEBP(4)


def _is_webp(blob: bytes) -> bool:
    """RIFF....WEBP — a container whose signature is split across two ranges."""
    return len(blob) >= _WEBP_HEADER_LEN and blob[:4] == b"RIFF" and blob[8:12] == b"WEBP"


# Bytes that count as "text" in a printable-ratio test: tab/newline/CR plus the
# printable ASCII range plus the printable Latin-1 high range (covers cp1252
# prose). NUL and most control/binary bytes are excluded.
_TEXTISH = frozenset({0x09, 0x0A, 0x0D, *range(0x20, 0x7F), *range(0xA0, 0x100)})
_PRINTABLE_FLOOR = 0.90


def _looks_textual(head: bytes) -> bool:
    """Accept a no-signature blob as text only if it is decodable prose.

    Clean UTF-8 is text outright; otherwise it must be NUL-free and overwhelmingly
    printable (cp1252/Latin-1 prose). Anything else is a binary blob we cannot
    safely call text, so the caller routes it to UNKNOWN → fail closed.
    """
    if b"\x00" in head:
        return False
    try:
        head.decode("utf-8")
    except UnicodeDecodeError:
        printable = sum(1 for byte in head if byte in _TEXTISH)
        if not head or printable / len(head) < _PRINTABLE_FLOOR:
            return False
    return True


def sniff(blob: bytes) -> DocKind:
    """Route an untrusted blob to a parser class from its leading bytes."""
    if not blob:
        return DocKind.UNKNOWN
    for prefix, kind in _PREFIX_KINDS:
        if blob.startswith(prefix):
            return kind
    if any(blob.startswith(sig) for sig in _IMAGE_SIGNATURES) or _is_webp(blob):
        return DocKind.IMAGE

    marker_head = blob[:512].lstrip().lower()
    if any(marker_head.startswith(marker) for marker in _HTML_MARKERS):
        return DocKind.HTML

    return DocKind.TEXT if _looks_textual(blob[:8192]) else DocKind.UNKNOWN
