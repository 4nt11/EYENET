"""Embedded-metadata logic in the stdlib in-jail workers (RTF info, HTML meta).

The PDF/DOCX/image workers import venv-only libs (fitz/docx/PIL) and are proven
by the real-jail smoke; the RTF + HTML workers are pure stdlib, so their new
metadata extraction is unit-testable directly. (These modules live under
``_workers`` and are coverage-omitted — this test asserts correctness, not cov.)
"""

from __future__ import annotations

import pytest

from eyenet.classifier.extract._workers.html_worker import _TextExtractor
from eyenet.classifier.extract._workers.rtf_worker import extract_info

pytestmark = pytest.mark.unit


def test_rtf_info_fields_extracted() -> None:
    rtf = r"{\rtf1{\info{\title Secret Plan}{\author Jane Doe}{\operator ops}}\par body}"
    info = extract_info(rtf)
    assert info["title"] == "Secret Plan"
    assert info["author"] == "Jane Doe"
    assert info["operator"] == "ops"


def test_rtf_custom_destination_company_extracted() -> None:
    # The {\*\company …} custom-destination form.
    info = extract_info(r"{\rtf1{\info{\*\company Acme Corp}}body}")
    assert info["company"] == "Acme Corp"


def test_rtf_no_info_group_is_empty() -> None:
    assert extract_info(r"{\rtf1 just body text\par}") == {}


def test_rtf_empty_field_dropped() -> None:
    assert "title" not in extract_info(r"{\rtf1{\info{\title }}body}")


def test_html_title_and_meta_captured() -> None:
    html = (
        "<html><head><title>Quarterly Brief</title>"
        '<meta name="author" content="J. Smith">'
        '<meta property="og:description" content="leak">'
        "</head><body>visible</body></html>"
    )
    parser = _TextExtractor()
    parser.feed(html)
    assert "".join(parser.title_parts).strip() == "Quarterly Brief"
    assert parser.meta_tags["author"] == "J. Smith"
    assert parser.meta_tags["og:description"] == "leak"
    assert "visible" in parser.parts


def test_html_meta_without_content_ignored() -> None:
    parser = _TextExtractor()
    parser.feed('<meta name="viewport">')
    assert parser.meta_tags == {}
