"""In-jail HTML text extractor (stdlib html.parser). Runs ONLY inside nsjail.

Strips tags and drops <script>/<style> content, emitting visible text as the
{"text", "meta"} envelope. No third-party imports — runs under the base profile.

M10 slice 7: also surfaces the <title> and <meta name=…/property=… content=…>
tags under ``meta.embedded`` (author/description/keywords/generator/OpenGraph).
ATTACKER-CONTROLLED — captured verbatim, sanitized HOST-SIDE. All values are
strings (JSON-safe).
"""

import json
import sys
from html.parser import HTMLParser

_DROP_TAGS = frozenset({"script", "style"})


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._in_title = False
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self.meta_tags: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag in _DROP_TAGS:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True
        elif tag == "meta":
            pairs = {k.lower(): v for k, v in attrs if v is not None}  # type: ignore[union-attr]
            key = pairs.get("name") or pairs.get("property") or pairs.get("http-equiv")
            content = pairs.get("content")
            if key and content:
                self.meta_tags[key.lower()] = content

    def handle_endtag(self, tag: str) -> None:
        if tag in _DROP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)
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

    embedded: dict[str, object] = {}
    title = "".join(parser.title_parts).strip()
    if title:
        embedded["title"] = title
    if parser.meta_tags:
        embedded["meta_tags"] = parser.meta_tags

    meta = {"method": "html", "embedded": embedded}
    sys.stdout.write(json.dumps({"text": text, "meta": meta}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
