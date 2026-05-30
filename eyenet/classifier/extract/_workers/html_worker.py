"""In-jail HTML text extractor (stdlib html.parser). Runs ONLY inside nsjail.

Strips tags and drops <script>/<style> content, emitting visible text as the
{"text", "meta"} envelope. No third-party imports — runs under the base profile.
"""

import json
import sys
from html.parser import HTMLParser

_DROP_TAGS = frozenset({"script", "style"})


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag in _DROP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in _DROP_TAGS and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            stripped = data.strip()
            if stripped:
                self.parts.append(stripped)


def main() -> int:
    with open("/input", "rb") as handle:
        data = handle.read()
    try:
        markup = data.decode("utf-8")
    except UnicodeDecodeError:
        markup = data.decode("latin-1")
    parser = _TextExtractor()
    parser.feed(markup)
    text = "\n".join(parser.parts)
    sys.stdout.write(json.dumps({"text": text, "meta": {"method": "html"}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
