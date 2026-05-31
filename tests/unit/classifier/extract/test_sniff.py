"""Magic-byte routing: content decides the parser, never the extension."""

from __future__ import annotations

import pytest

from eyenet.classifier.extract._sniff import DocKind, sniff

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("blob", "expected"),
    [
        (b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n", DocKind.PDF),
        (b"PK\x03\x04\x14\x00\x06\x00", DocKind.ZIP_OOXML),
        (b"{\\rtf1\\ansi hello}", DocKind.RTF),
        (b"\x89PNG\r\n\x1a\n\x00\x00", DocKind.IMAGE),
        (b"\xff\xd8\xff\xe0\x00\x10JFIF", DocKind.IMAGE),
        (b"II*\x00\x08\x00\x00\x00", DocKind.IMAGE),
        (b"MM\x00*\x00\x00\x00\x08", DocKind.IMAGE),
        (b"GIF89a\x01\x00", DocKind.IMAGE),
        (b"BM\x8a\x00\x00\x00", DocKind.IMAGE),
        (b"RIFF\x24\x00\x00\x00WEBPVP8 ", DocKind.IMAGE),
        (b"<!DOCTYPE html><html><body>hi", DocKind.HTML),
        (b"  \n<html lang='es'>hola</html>", DocKind.HTML),
        (b"<?xml version='1.0'?><html/>", DocKind.HTML),
        (b"just some plain prose, nothing special", DocKind.TEXT),
        ("café programa secreto".encode("latin-1"), DocKind.TEXT),
        (b"", DocKind.UNKNOWN),
        (b"\x00\x01\x02\x03\x04binary\x00stuff", DocKind.UNKNOWN),
        (bytes(range(256)) * 4, DocKind.UNKNOWN),
    ],
)
def test_sniff_routes_by_signature(blob: bytes, expected: DocKind) -> None:
    assert sniff(blob) == expected


def test_sniff_ignores_extension_a_pdf_is_a_pdf() -> None:
    # A blob whose "name" would say .txt is still a PDF by its bytes.
    assert sniff(b"%PDF-1.4 dressed up as a text file") is DocKind.PDF


def test_sniff_nul_bytes_force_unknown_even_without_signature() -> None:
    # A NUL early in an otherwise printable blob is a strong binary tell.
    assert sniff(b"mostly text\x00but binary") is DocKind.UNKNOWN


def test_sniff_truncated_webp_is_not_misread() -> None:
    # RIFF without the WEBP tag is not an image; printable -> text, else unknown.
    assert sniff(b"RIFF") in (DocKind.TEXT, DocKind.UNKNOWN)
