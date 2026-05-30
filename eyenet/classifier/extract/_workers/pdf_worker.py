"""In-jail PDF text-layer extractor (PyMuPDF). Runs ONLY inside nsjail.

Imports ``fitz`` from the eyenet-extract venv (bound RO, on PYTHONPATH). Reads
/input, concatenates the per-page text layer, and emits the {"text", "meta"}
envelope. An encrypted/password-protected document exits non-zero so the
chokepoint fails it closed (a locked document is a signal, not a benign empty).
A malformed PDF raises out of fitz.open → non-zero exit → fail closed.

This slice extracts the TEXT LAYER only; embedded-image OCR + text-vs-render
mismatch are Slice 2b.
"""

import json
import sys

import fitz


def main() -> int:
    with open("/input", "rb") as handle:
        data = handle.read()
    doc = fitz.open(stream=data, filetype="pdf")
    if doc.needs_pass:
        sys.stderr.write("pdf is encrypted / password-protected\n")
        return 2
    parts = [page.get_text() for page in doc]
    text = "\n".join(parts)
    meta = {"method": "pymupdf", "pages": doc.page_count}
    sys.stdout.write(json.dumps({"text": text, "meta": meta}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
