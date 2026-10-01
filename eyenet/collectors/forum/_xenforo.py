# SPDX-License-Identifier: AGPL-3.0-or-later
"""XenForo thread parser.

Sibling of :mod:`._mybb`: same :class:`ParsedPost` contract and the same flat
function surface the collector calls, reversed from XenForo's DOM instead of
MyBB's. Parsing walks the DOM with ``html5lib`` + BeautifulSoup selectors — no
regex on markup — so hostile BBCode can't corrupt an evidence field.

Selector contract reversed from a real XenForo board (nodo313.net, XF2 with a
Spanish locale and CUSTOM friendly-URL routes):

- post container   ``article.message--post``        -> pid from
                                                       ``data-content="post-<pid>"``
- author identity  article ``data-author`` attr     -> the actor_key seed
                                                       (stable, theme-independent)
- author display   ``.message-name``                -> name as shown
- timestamp        ``time[datetime]`` (ISO-8601)     -> TZ-AWARE (XF emits the
                                                       real offset); falls back to
                                                       the ``data-time`` epoch
- edited marker    ``.message-lastEdit``             -> present when edited
- body             ``.message-userContent .bbWrapper``
- thread id (tid)  ``data-content-key="thread-<id>"`` / canonical URL ``.<id>/``

Two traps this parser is built to survive, because XenForo config is per-instance:

1. **Route words are customized.** nodo313 serves forums at ``/foros/<slug>/``
   and threads at ``/post/<slug>.<id>/`` — NOT XenForo's default ``/forums/`` and
   ``/threads/``. So link discovery matches STRUCTURE (``.node--forum``,
   ``.structItem--thread``), never a ``/threads/`` substring, and pulls the id
   from the numeric URL suffix.
2. **Labels are localized.** Thread-list meta reads ``Respuestas`` (es), not
   ``Replies``. Nothing here matches on visible label text.

INTEGRATION NOTE — unlike :mod:`._mybb` (board-local *naive* ``posted_at`` that
the collector tz-attaches), XenForo ``posted_at`` is already **tz-aware UTC-
anchored**. The collector must NOT apply a source-tz offset to XenForo rows.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from bs4.element import Tag

from eyenet.collectors.forum._post import ParsedPost

# Hidden-content addons (XF has no core [hide]; themes bolt one on). Best-effort
# text match on the common rendered notice, es + en. Linear alternation, no
# backtracking blowup. ponytail: widen when a save shows a real gated post —
# the exact notice string is addon-specific.
_HIDE_GATE = re.compile(
    r"(?:reply to (?:this )?thread to view|hidden content|contenido oculto"
    r"|responde para ver)",
    re.IGNORECASE,
)

# tid embedded in a friendly-URL slug: "...slug.60371/" or "...slug.60371".
_URL_TID = re.compile(r"\.(\d+)/?$")


def _cf_decode(hexs: str) -> str:
    """Decode a Cloudflare cf_email hex string to the real address.

    Same XOR scheme as MyBB-behind-Cloudflare: the obfuscated emails ARE the
    leaked PII this collector exists to capture, so recovering them matters.
    """
    try:
        raw = bytes.fromhex(hexs)
    except ValueError:
        return ""
    if not raw:
        return ""
    key = raw[0]
    return "".join(chr(b ^ key) for b in raw[1:])


def _decode_cf_emails(node: Tag) -> None:
    """Replace Cloudflare-obfuscated email links in-place with the real address."""
    for a in node.select("a.__cf_email__"):
        hexs = a.get("data-cfemail")
        if isinstance(hexs, str):
            decoded = _cf_decode(hexs)
            if decoded:
                a.replace_with(decoded)
    for a in node.select('a[href*="/cdn-cgi/l/email-protection#"]'):
        href = str(a.get("href", ""))
        decoded = _cf_decode(href.split("#", 1)[-1])
        if decoded:
            a.replace_with(decoded)


def _parse_date(raw: str) -> datetime | None:
    """XF ``time[datetime]`` is ISO-8601 with a real offset -> tz-aware datetime.

    ``datetime.fromisoformat`` handles the offset (Py>=3.11 also 'Z'). Returns
    None on anything unparseable so the caller keeps the raw string for audit.
    """
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _epoch_to_dt(epoch: str) -> datetime | None:
    """Fallback: XF ``data-time`` unix epoch -> tz-aware UTC datetime."""
    if not epoch.isdigit():
        return None
    return datetime.fromtimestamp(int(epoch), tz=UTC)


def _canonical(href: str) -> str:
    """Strip query + fragment, keep scheme/host/path so links dedupe to one form."""
    p = urlparse(href)
    base = f"{p.scheme}://{p.netloc}" if p.netloc else ""
    return f"{base}{p.path}"


def parse_thread(html: str) -> list[ParsedPost]:
    """Parse a XenForo thread page into its posts, in document order."""
    soup = BeautifulSoup(html, "html5lib")
    posts: list[ParsedPost] = []

    for container in soup.select("article.message--post"):
        content = str(container.get("data-content", ""))
        pid = content.removeprefix("post-")
        if not pid or pid == content:  # not a "post-<id>" marker
            continue

        author_username = str(container.get("data-author", "")).strip()
        name_el = container.select_one(".message-name")
        author_display = name_el.get_text(strip=True) if name_el else author_username

        time_el = container.select_one("time[datetime], time[data-time]")
        posted_raw = ""
        posted_at: datetime | None = None
        if time_el is not None:
            iso = str(time_el.get("datetime", "")).strip()
            epoch = str(time_el.get("data-time", "")).strip()
            posted_raw = iso or epoch
            posted_at = _parse_date(iso) if iso else None
            if posted_at is None:
                posted_at = _epoch_to_dt(epoch)

        edit_el = container.select_one(".message-lastEdit")
        edited = bool(edit_el and edit_el.get_text(strip=True))

        # First .bbWrapper inside this post's own content (not a nested quote's).
        body = container.select_one(".message-userContent .bbWrapper")
        if body is None:
            body = container.select_one(".bbWrapper")
        if body is not None:
            _decode_cf_emails(body)
        body_html = body.decode_contents() if body else ""
        if body is not None:
            # Strip quoted blocks so body_text is the poster's OWN words — a reply
            # quoting a breach dump must not be classified as a breach dump.
            for quote in body.select("blockquote.bbCodeBlock--quote"):
                quote.decompose()
            body_text = body.get_text("\n", strip=True)
        else:
            body_text = ""

        posts.append(
            ParsedPost(
                pid=pid,
                author_username=author_username,
                author_display=author_display,
                posted_at=posted_at,
                posted_raw=posted_raw,
                edited=edited,
                body_text=body_text,
                body_html=body_html,
                reply_gated=bool(_HIDE_GATE.search(body_text)),
            )
        )

    return posts


def parse_forum_links(html: str) -> list[str]:
    """Forum (board) URLs from a XenForo node list, in order, deduped.

    The operator-monitorable units (GroupKind.FORUM_CATEGORY). Scoped to
    ``.node--forum`` title anchors so category headers, breadcrumbs and the
    global nav (which also carry node hrefs) don't leak in. Route-word agnostic:
    takes whatever href the title anchor holds (``/forums/..`` or ``/foros/..``).
    """
    soup = BeautifulSoup(html, "html5lib")
    out: list[str] = []
    seen: set[str] = set()
    for node in soup.select(".node--forum"):
        anchor = node.select_one(".node-title a[href]")
        if anchor is None:
            continue
        canon = _canonical(str(anchor.get("href", "")))
        if canon and canon not in seen:
            seen.add(canon)
            out.append(canon)
    return out


def parse_subforum_links(html: str) -> list[str]:
    """Child subforum URLs from a XenForo forum page, in order, deduped.

    Scoped to the inline sub-forum list (``.node-subNodeFlatList``) so it returns
    ONLY this forum's children, mirroring the MyBB parser's
    ``table.forum-display__subforums`` scoping. Children surface as their own
    monitorable FORUM_CATEGORY; the operator chooses whether any get crawled.
    Empty when the board has no inline subforum list.
    """
    soup = BeautifulSoup(html, "html5lib")
    out: list[str] = []
    seen: set[str] = set()
    for anchor in soup.select(".node-subNodeFlatList a[href]"):
        canon = _canonical(str(anchor.get("href", "")))
        if canon and canon not in seen:
            seen.add(canon)
            out.append(canon)
    return out


def parse_thread_links(html: str) -> list[str]:
    """Thread URLs from a XenForo forum page, in order, deduped.

    Scoped to ``.structItem--thread`` title anchors so preview/unread/author
    links in the same row don't duplicate the thread. Query/fragment stripped.
    """
    soup = BeautifulSoup(html, "html5lib")
    out: list[str] = []
    seen: set[str] = set()
    for row in soup.select(".structItem--thread"):
        anchor = row.select_one(".structItem-title a[href]")
        if anchor is None:
            continue
        canon = _canonical(str(anchor.get("href", "")))
        if canon and canon not in seen:
            seen.add(canon)
            out.append(canon)
    return out


def parse_canonical_tid(html: str) -> str | None:
    """The board's stable numeric thread id (tid) from a thread page, or None.

    XF friendly-URL slugs re-slug on rename, but the tid is invariant. Two
    independent sources: the per-element ``data-content-key="thread-<id>"`` XF
    emits, and the ``.<id>/`` suffix of the canonical/og:url. Prefer the
    attribute (exact), fall back to the URL suffix.
    """
    soup = BeautifulSoup(html, "html5lib")
    el = soup.select_one('[data-content-key^="thread-"]')
    if el is not None:
        key = str(el.get("data-content-key", "")).removeprefix("thread-")
        if key.isdigit():
            return key
    link = soup.select_one('link[rel="canonical"][href]')
    href = str(link.get("href", "")) if link else ""
    if not href:
        meta = soup.select_one('meta[property="og:url"][content]')
        href = str(meta.get("content", "")) if meta else ""
    m = _URL_TID.search(urlparse(href).path)
    return m.group(1) if m else None


def parse_thread_title(html: str) -> str | None:
    """The thread subject from ``h1.p-title-value`` (clean, no site suffix).

    Falls back to ``<title>`` then None. Capture from page 1; later pages carry
    the same subject.
    """
    soup = BeautifulSoup(html, "html5lib")
    h1 = soup.select_one("h1.p-title-value")
    if h1 is not None:
        title = h1.get_text(strip=True)
        if title:
            return title
    if soup.title is not None:
        title = soup.title.get_text(strip=True)
        return title or None
    return None


def thread_page_count(html: str) -> int:
    """Highest ``/page-N`` in a XenForo thread's pageNav block (>= 1).

    XF paginates with ``.../page-<N>`` path segments (not a query param), so the
    count is read off the pageNav anchors' paths. A thread with no pageNav is a
    single page.
    """
    soup = BeautifulSoup(html, "html5lib")
    max_page = 1
    for anchor in soup.select(".pageNav-page a[href], .pageNav a[href]"):
        m = re.search(r"/page-(\d+)", urlparse(str(anchor.get("href", ""))).path)
        if m:
            max_page = max(max_page, int(m.group(1)))
    return max_page


@dataclass(frozen=True)
class ReplyForm:
    """Per-session tokens a XenForo reply POST needs. Mirrors _mybb.ReplyForm.

    XF guards writes with ``_xfToken`` (CSRF). Scraped fresh from the thread page
    immediately before a POST. EYENET does no login automation, so for a guest
    session this is typically absent -> None, and the caller fails closed.
    """

    xf_token: str
    tid: str


def parse_reply_form(html: str) -> ReplyForm | None:
    """Scrape XF reply tokens from a thread page. None if absent (fail closed)."""
    soup = BeautifulSoup(html, "html5lib")
    el = soup.select_one('input[name="_xfToken"]')
    xf_token = str(el.get("value", "")).strip() if el is not None else ""
    tid = parse_canonical_tid(html)
    if not (xf_token and tid):
        return None
    return ReplyForm(xf_token=xf_token, tid=tid)


__all__ = ["ParsedPost", "parse_thread", "thread_page_count"]
