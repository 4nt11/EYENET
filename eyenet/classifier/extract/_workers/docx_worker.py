"""In-jail DOCX text extractor (python-docx). Runs ONLY inside nsjail.

Imports ``docx`` from the eyenet-extract venv (bound RO, on PYTHONPATH). Reads
/input, gathers paragraph text plus table-cell text, and emits the
{"text", "meta"} envelope. A non-DOCX zip (or corrupt file) raises out of
docx.Document → non-zero exit → fail closed.
"""

import io
import json
import sys

import docx


def main() -> int:
    with open("/input", "rb") as handle:
        data = handle.read()
    document = docx.Document(io.BytesIO(data))
    parts = [paragraph.text for paragraph in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                parts.append(cell.text)
    text = "\n".join(part for part in parts if part)
    sys.stdout.write(json.dumps({"text": text, "meta": {"method": "python-docx"}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
