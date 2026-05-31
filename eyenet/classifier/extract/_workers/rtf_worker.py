"""In-jail RTF text extractor (stdlib only). Runs ONLY inside nsjail.

A minimal RTF-to-text stripper: it drops control words and ignorable
destinations (font tables, stylesheets, embedded objects), decodes \\'hh hex and
\\uN unicode escapes, and keeps the visible text. Not a full RTF reader — enough
to surface text for classification. No third-party imports.

M10 slice 7: also surfaces the ``{\\info}`` group's text fields (title/author/
operator/company/…) under ``meta.embedded``. ATTACKER-CONTROLLED — captured
verbatim, sanitized HOST-SIDE. A focused regex pulls the single-level info
subgroups; nested date control words (\\creatim) are out of scope for this pass.
"""

import json
import re
import sys

_TOKEN = re.compile(
    r"\\([a-z]{1,32})(-?\d{1,10})?[ ]?|\\'([0-9a-fA-F]{2})|\\([^a-zA-Z])|([{}])|[\r\n]+|(.)",
)

# Control words whose group content is metadata/binary, not document text.
_IGNORE_DESTINATIONS = frozenset(
    {
        "fonttbl", "colortbl", "stylesheet", "info", "pict", "object",
        "themedata", "colorschememapping", "rsidtbl", "generator",
        "latentstyles", "datastore", "mmath", "header", "footer",
    }
)

# Control words that emit a literal character.
_SPECIAL = {
    "par": "\n", "sect": "\n", "page": "\n", "line": "\n", "tab": "\t",
    "emdash": "—", "endash": "–", "lquote": "‘",
    "rquote": "’", "ldblquote": "“", "rdblquote": "”",
    "bullet": "•", "nbsp": " ",
}


# Single-level {\info} text fields, incl. the {\*\company …} custom-destination
# form. Values are plain text (no nested groups), so [^{}]* is sufficient.
_INFO_RE = re.compile(
    r"\{(?:\\\*)?\\(title|author|subject|operator|company|manager|keywords|comment|doccomm)"
    r"\s+([^{}]*)\}"
)


def extract_info(rtf: str) -> dict[str, str]:
    """Pull the {\\info} group's text fields. Best-effort, never raises."""
    out: dict[str, str] = {}
    for match in _INFO_RE.finditer(rtf):
        field, value = match.group(1), match.group(2).strip()
        if value:
            out[field] = value
    return out


def rtf_to_text(rtf: str) -> str:
    stack: list[tuple[int, bool]] = []
    ucskip = 1
    curskip = 0
    ignorable = False
    out: list[str] = []
    for match in _TOKEN.finditer(rtf):
        word, arg, hexc, special, brace, char = match.groups()
        if brace == "{":
            stack.append((ucskip, ignorable))
        elif brace == "}":
            if stack:
                ucskip, ignorable = stack.pop()
        elif special is not None:
            if special == "*":
                ignorable = True
            elif not ignorable and special in "\\{}":
                out.append(special)
            elif not ignorable and special == "~":
                out.append(" ")
        elif word is not None:
            if word in _IGNORE_DESTINATIONS:
                ignorable = True
            elif word == "uc":
                ucskip = int(arg) if arg else 1
            elif word == "u":
                if arg is not None:
                    code = int(arg)
                    if code < 0:
                        code += 65536
                    if not ignorable:
                        out.append(chr(code))
                    curskip = ucskip
            elif word in _SPECIAL and not ignorable:
                out.append(_SPECIAL[word])
        elif hexc is not None:
            if curskip > 0:
                curskip -= 1
            elif not ignorable:
                out.append(bytes([int(hexc, 16)]).decode("latin-1"))
        elif char is not None:
            if curskip > 0:
                curskip -= 1
            elif not ignorable:
                out.append(char)
    return "".join(out)


def main() -> int:
    with open("/input", "rb") as handle:
        data = handle.read()
    rtf = data.decode("latin-1")
    text = rtf_to_text(rtf)
    meta = {"method": "rtf", "embedded": extract_info(rtf)}
    sys.stdout.write(json.dumps({"text": text, "meta": meta}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
