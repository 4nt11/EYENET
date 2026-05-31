"""Neutralize untrusted model output at the data-model boundary.

The LLM's free text (summary, indicators, error details) is HOSTILE DATA: a
local model can emit ``<script>``, an ANSI escape, a NUL byte, or a broken tag
that detonates later in a review UI, an audit viewer, a PDF report, or a
terminal tailing structlog. "Today's ``<script>`` is tomorrow's CVE." This is a
*different* threat from prompt injection (which corrupts control flow) — this is
stored-XSS / log-injection / terminal-escape.

So we neutralize here, once, where model text enters our types — before it is
ever stored or logged. The transform is deliberately conservative: it produces
an inert, bounded, single-line plain-text string no sink can be tricked by. It
is **defense in depth**, not a substitute — render sinks must STILL context-encode;
this is the fail-safe for the day one of them forgets.

We *escape* angle brackets rather than *strip* tags: stripping is bypassable
(``<scr<script>ipt>`` survives a naive strip), HTML-entity escaping is
unconditional — a ``<`` always becomes ``&lt;`` and no tag can ever form.
"""

from __future__ import annotations

import html
import re
import unicodedata

__all__ = ["sanitize_model_text"]

# ANSI / CSI escape sequences (terminal control). Strip BEFORE the generic
# control-char pass so ``\x1b[31m`` vanishes whole instead of leaving ``[31m``.
# Covers 7-bit CSI (``\x1b[ … final``), other Fe escapes (``\x1b@``..``\x1b_``),
# and the 8-bit C1 CSI introducer (``\x9b``).
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[@-Z\\-_]|\x9b[0-9;?]*[ -/]*[@-~]")

# C0 controls (incl. NUL, and \t\n\r), DEL, and C1 controls → replaced with a
# space (then collapsed). Nothing control-plane survives into stored text.
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")

_WS = re.compile(r"\s+")


def sanitize_model_text(s: str, *, max_len: int) -> str:
    """Return an inert, bounded, single-line plain-text form of model output.

    NFC-normalize → strip ANSI/CSI → controls→space → collapse whitespace → cap
    length → HTML-entity-escape ``& < > " '``. Truncation happens *before*
    escaping so an entity is never split mid-sequence (``&lt`` -> ``&l``).
    """
    s = unicodedata.normalize("NFC", s)
    s = _ANSI.sub("", s)
    s = _CONTROL.sub(" ", s)
    s = _WS.sub(" ", s).strip()
    if len(s) > max_len:
        s = s[:max_len].rstrip()
    return html.escape(s, quote=True)
