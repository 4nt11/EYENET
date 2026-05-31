"""In-jail image EXIF extractor (Pillow). Runs ONLY inside nsjail.

The second of the IMAGE two-pass: Tesseract (a separate jail entrypoint) reads
the OCR text; THIS worker reads the EXIF metadata. They are separate passes
because the jail KILLs ``clone``/``fork`` — a Python worker cannot shell out to
the ``tesseract`` binary, so OCR and EXIF cannot share one process.

Imports ``PIL`` from the eyenet-extract venv (bound RO, on PYTHONPATH). Reads
/input, pulls the base IFD0 + the Exif sub-IFD (DateTimeOriginal, Make, Model,
Software, GPS pointer), and emits a ``{"text": "", "meta": {...}}`` envelope.

EXIF values are ATTACKER-CONTROLLED and arrive as a zoo of types (int, str,
bytes, IFDRational, nested tuples). Every value is coerced to a JSON-safe form
HERE — an un-coercible value emitting from ``json.dumps`` would crash the worker.
Host-side, the values are additionally sanitized before any log/store.

Pillow does local header parsing only (no network/DNS/threads), so it runs under
the base allowlist + single-thread env like the other venv workers.
"""

import json
import sys

from PIL import ExifTags, Image


def _json_safe(value: object) -> object:
    """Coerce an arbitrary EXIF value into something ``json.dumps`` accepts."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, bytes):
        return value.decode("latin-1", "replace")
    if isinstance(value, (tuple, list)):
        return [_json_safe(item) for item in value]
    # IFDRational and any other exotic type → string form.
    return str(value)


def _collect(exif: "Image.Exif") -> dict[str, object]:
    out: dict[str, object] = {}
    for tag_id, value in exif.items():
        name = ExifTags.TAGS.get(tag_id, str(tag_id))
        out[name] = _json_safe(value)
    # The Exif sub-IFD holds DateTimeOriginal, LensModel, etc.
    sub = exif.get_ifd(ExifTags.IFD.Exif)
    for tag_id, value in sub.items():
        name = ExifTags.TAGS.get(tag_id, str(tag_id))
        out.setdefault(name, _json_safe(value))
    return out


def main() -> int:
    with open("/input", "rb") as handle:
        image = Image.open(handle)
        exif = image.getexif()
    embedded = _collect(exif) if exif else {}
    meta = {"method": "pillow-exif", "exif": embedded}
    sys.stdout.write(json.dumps({"text": "", "meta": meta}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
