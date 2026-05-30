"""In-jail plain-text extractor (stdlib only). Runs ONLY inside nsjail.

Reads /input, decodes as UTF-8 (falling back to Latin-1), and emits the
{"text", "meta"} envelope. No third-party imports — runs under the base profile.
"""

import json
import sys


def main() -> int:
    with open("/input", "rb") as handle:
        data = handle.read()
    try:
        text = data.decode("utf-8")
        encoding = "utf-8"
    except UnicodeDecodeError:
        text = data.decode("latin-1")
        encoding = "latin-1"
    sys.stdout.write(json.dumps({"text": text, "meta": {"method": "text", "encoding": encoding}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
