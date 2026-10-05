# SPDX-License-Identifier: AGPL-3.0-or-later
"""MyBB thread parser.

Turns a saved/fetched MyBB thread page into structured :class:`ParsedPost` rows.
Parsing uses ``html5lib`` (WHATWG-spec tree construction, browser-faithful on
malformed markup) behind BeautifulSoup's selector API. No regex on markup: the
DOM is walked with CSS selectors so hostile/broken BBCode can't silently corrupt
an evidence field.

Selector contract reversed from real darkforums.as (MyBB SEO-URL theme):

- post container   ``div.post[id^="post_"]``      -> pid is the id suffix
- author identity  ``.post_user-profile a``       -> ``/User-<slug>`` (no uids
                                                     in this theme; slug is the
                                                     actor_key seed)
- timestamp        ``span.post_date`` direct text  -> ``DD-MM-YY, hh:mm AM/PM``
                                                     (board-local; see tz note)
- edited marker    ``span.post_edit``              -> non-empty when edited
- body             ``div.post_body``               -> text + inner HTML
- permalink        anchor href ``?pid=<pid>#pid<pid>`` (evidence_ref tail)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup
from bs4.element import NavigableString, Tag

from eyenet.collectors.forum._post import ParsedPost

# MyBB [hide] plugin gate: content is locked until the viewer replies. Text
# match on the rendered notice ("You must reply to this thread to view this
# content"). Linear alternation, no backtracking blowup on adversarial bodies.
_HIDE_GATE = re.compile(r"reply to (?:this )?thread to view", re.IGNORECASE)

# MyBB renders absolute post times in the viewer's board timezone. As an
# unauthenticated/guest collector we get the board default; the true UTC offset
# is a per-source calibration knob, not a parser concern. We parse to a NAIVE
# datetime and let the collector attach the source tz.
# MyBB also emits RELATIVE dates ("Today, 10:56 PM" / "Yesterday, ..." / "2 hours
# ago") under some settings — raidforums does for fresh posts. _parse_date handles
# these too; a real parsed value means the collector's date-fallback-to-now() ERROR
# guard (recency is load-bearing) does NOT fire on the newest, highest-value posts.
_DATE_FMT = "%d-%m-%y, %I:%M %p"
_TIME_FMT = "%I:%M %p"  # the time tail shared by "Today,"/"Yesterday," forms
_REL_UNITS = {
    "second": 1,
    "sec": 1,
    "minute": 60,
    "min": 60,
    "hour": 3600,
    "day": 86400,
    "week": 604800,
}
# "3 hours ago" / "1 minute ago" / "a day ago" / "an hour ago"
_REL_RE = re.compile(
    r"^(?:(?P<n>\d+)|an?)\s+(?P<unit>second|sec|minute|min|hour|day|week)s?\s+ago$", re.I
)


def _cf_decode(hexs: str) -> str:
    """Decode a Cloudflare cf_email hex string to the real address.

    Cloudflare XORs the email bytes with the first byte as the key. Recovering it
    matters: the obfuscated emails ARE the leaked PII this collector exists to
    capture; storing "[email protected]" is silent data loss.
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
    # Some themes stash the hex on the href fragment of a protection link.
    for a in node.select('a[href*="/cdn-cgi/l/email-protection#"]'):
        href = str(a.get("href", ""))
        decoded = _cf_decode(href.split("#", 1)[-1])
        if decoded:
            a.replace_with(decoded)


def _username_slug(href: str) -> str:
    """``https://host/User-xNov`` or ``User-xNov`` -> ``xNov``."""
    tail = href.rstrip("/").rsplit("/", 1)[-1]
    return tail.split("User-", 1)[-1] if "User-" in tail else tail


def _parse_date(raw: str, *, now: datetime | None = None) -> datetime | None:
    """Parse a MyBB post timestamp to a NAIVE board-local datetime, or None.

    Absolute (`_DATE_FMT`) first, then the relative renderings ("Today, HH:MM AM/PM",
    "Yesterday, ...", "N minutes/hours/days ago", "an hour ago"). A relative parse
    yields a REAL timestamp (not a now()-substitution), so the collector's recency
    guard stays quiet. `now` is injectable for tests; defaults to the board-local
    naive clock to match `_DATE_FMT`.
    """
    raw = raw.strip()
    try:
        return datetime.strptime(raw, _DATE_FMT)  # noqa: DTZ007 - board-local naive, see module note
    except ValueError:
        pass
    ref = now or datetime.now()  # noqa: DTZ005 - board-local naive, matches _DATE_FMT
    low = raw.lower()
    for word, days_back in (("today", 0), ("yesterday", 1)):
        if low.startswith(word):
            try:
                t = datetime.strptime(raw[len(word) :].lstrip(" ,"), _TIME_FMT)  # noqa: DTZ007
            except ValueError:
                return None
            d = (ref - timedelta(days=days_back)).date()
            return datetime(d.year, d.month, d.day, t.hour, t.minute)  # noqa: DTZ001 - naive
    m = _REL_RE.match(low)
    if m:
        n = int(m.group("n")) if m.group("n") else 1
        return ref - timedelta(seconds=n * _REL_UNITS[m.group("unit")])
    return None


def _direct_text(node: Tag) -> str:
    """First direct (non-descendant) text of a node, stripped.

    ``post_date`` holds the date as a direct string then nests the (usually
    empty) ``post_edit`` span; we want only the direct string.
    """
    for child in node.children:
        if isinstance(child, NavigableString):
            text = child.strip()
            if text:
                return text
    return ""


def parse_thread(html: str) -> list[ParsedPost]:
    """Parse a MyBB thread page into its posts, in document order."""
    soup = BeautifulSoup(html, "html5lib")
    posts: list[ParsedPost] = []

    for container in soup.select('div.post[id^="post_"]'):
        pid = str(container.get("id", "")).removeprefix("post_")
        if not pid:
            continue

        # Author profile anchor. Themes vary the block class between
        # ``post_user-profile`` (darkforums) and the BEM ``post__user-profile``
        # (pwnforums) — match both or every post collapses to one empty author.
        author_link = container.select_one(".post_user-profile a, .post__user-profile a")
        # A user-profile block can lead with an icon-only <a>; prefer the first
        # anchor whose href actually points at a /User- profile.
        for anchor in container.select(".post_user-profile a, .post__user-profile a"):
            href = str(anchor.get("href", ""))
            if "User-" in href:
                author_link = anchor
                break
        href = str(author_link.get("href", "")) if author_link else ""
        author_username = _username_slug(href) if href else ""
        author_display = author_link.get_text(strip=True) if author_link else ""

        date_span = container.select_one("span.post_date")
        posted_raw = _direct_text(date_span) if date_span else ""
        posted_at = _parse_date(posted_raw) if posted_raw else None

        edit_span = container.select_one("span.post_edit")
        edited = bool(edit_span and edit_span.get_text(strip=True))

        body = container.select_one("div.post_body")
        if body is not None:
            # Recover Cloudflare-obfuscated emails before capturing anything, so
            # both the evidence HTML and the classifier text hold the real address.
            _decode_cf_emails(body)
        # body_html keeps EVERYTHING (evidence-faithful), captured before we strip.
        body_html = body.decode_contents() if body else ""
        # body_text feeds the classifier/stylometry, so it must be the poster's
        # OWN words only: strip MyBB quote blocks (someone else's content). Without
        # this, a one-word reply quoting a breach dump gets tagged as a breach dump.
        if body is not None:
            for quote in body.select("blockquote.mycode_quote"):
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


def _canonical(href: str) -> str:
    """Strip query + fragment: ``Thread-x--9?pid=3#pid3`` -> ``Thread-x--9``.

    Keeps scheme/host/path so relative and absolute links dedupe to one form.
    """
    p = urlparse(href)
    base = f"{p.scheme}://{p.netloc}" if p.netloc else ""
    return f"{base}{p.path}"


def parse_forum_links(html: str) -> list[str]:
    """Category (forum) URLs from a MyBB board index, in order, deduped.

    ``<a href="Forum-<name>">`` / ``Forum-<name>--<fid>``. These are the
    operator-monitorable units (GroupKind.FORUM_CATEGORY).
    """
    soup = BeautifulSoup(html, "html5lib")
    out: list[str] = []
    seen: set[str] = set()
    for anchor in soup.select('a[href*="Forum-"]'):
        href = str(anchor.get("href", ""))
        if "Forum-" not in href:
            continue
        canon = _canonical(href)
        if canon and canon not in seen:
            seen.add(canon)
            out.append(canon)
    return out


def parse_subforum_links(html: str) -> list[str]:
    """Child subforum URLs from a MyBB forum-display page, in order, deduped.

    Scoped to the subforum block (``table.forum-display__subforums``) so it
    returns ONLY this forum's children, never the global nav, breadcrumb,
    pagination, or column-sort anchors that also carry ``Forum-*`` hrefs (a
    whole-page ``a[href*="Forum-"]`` select picks up ~20 such decoys and would
    make recursion loop). Children surface as their own monitorable
    FORUM_CATEGORY; the operator chooses whether any get crawled.
    """
    soup = BeautifulSoup(html, "html5lib")
    out: list[str] = []
    seen: set[str] = set()
    for anchor in soup.select('table.forum-display__subforums a[href*="Forum-"]'):
        href = str(anchor.get("href", ""))
        if "Forum-" not in href:
            continue
        canon = _canonical(href)
        if canon and canon not in seen:
            seen.add(canon)
            out.append(canon)
    return out


def parse_canonical_tid(html: str) -> str | None:
    """The board's stable numeric thread id (tid) from a thread page, or None.

    DarkForums thread URLs are mostly tid-less SEO slugs, but the PAGE always
    carries the tid: the reply form's ``<input name="tid">`` and the per-post
    ``newreply.php?tid=<n>`` links. The tid is invariant across a move/re-slug,
    so it is the thread's true identity. Prefer the hidden input (exact), fall
    back to the first ``tid=<n>`` in a newreply link.
    """
    soup = BeautifulSoup(html, "html5lib")
    el = soup.select_one('input[name="tid"]')
    if el is not None:
        val = str(el.get("value", "")).strip()
        if val.isdigit():
            return val
    m = re.search(r"newreply\.php\?tid=(\d+)", html)
    return m.group(1) if m else None


def parse_thread_links(html: str) -> list[str]:
    """Thread URLs from a MyBB forum/category page, in order, deduped.

    ``<a href="Thread-<slug>--<tid>">``. Query/fragment stripped so a thread
    linked as both ``?action=lastpost`` and plain dedupe to one.
    """
    soup = BeautifulSoup(html, "html5lib")
    out: list[str] = []
    seen: set[str] = set()
    for anchor in soup.select('a[href*="Thread-"]'):
        href = str(anchor.get("href", ""))
        if "Thread-" not in href:
            continue
        canon = _canonical(href)
        if canon and canon not in seen:
            seen.add(canon)
            out.append(canon)
    return out


@dataclass(frozen=True)
class ReplyForm:
    """The per-session tokens a MyBB reply POST needs, scraped from newreply.php.

    ``my_post_key`` + ``posthash`` are single-use anti-CSRF/anti-dup tokens; they
    must be scraped fresh from the newreply GET immediately before the POST.
    """

    my_post_key: str
    posthash: str
    subject: str
    tid: str


def parse_reply_form(html: str) -> ReplyForm | None:
    """Scrape the reply-form tokens from a MyBB ``newreply.php`` page.

    Returns None if the form/tokens are absent (e.g. the session is not allowed
    to post, or the page is not a newreply page) so the caller fails closed
    rather than POSTing a reply with missing tokens.
    """
    soup = BeautifulSoup(html, "html5lib")

    def _val(name: str) -> str | None:
        el = soup.select_one(f'input[name="{name}"]')
        if el is None:
            return None
        v = el.get("value")
        return str(v) if v is not None else None

    my_post_key = _val("my_post_key")
    posthash = _val("posthash")
    tid = _val("tid")
    if not (my_post_key and posthash and tid):
        return None
    return ReplyForm(
        my_post_key=my_post_key,
        posthash=posthash,
        subject=_val("subject") or "",
        tid=tid,
    )


def parse_thread_title(html: str) -> str | None:
    """The thread subject from a MyBB thread page's ``<title>``.

    On this theme the ``<title>`` is the clean subject ("912,966 lines - URL
    LOGIN PASS ..."). Returns None when absent so the collector can fall back to
    the tid. Capture from page 1; later pages carry the same subject.
    """
    soup = BeautifulSoup(html, "html5lib")
    if soup.title is None:
        return None
    title = soup.title.get_text(strip=True)
    return title or None


def thread_page_count(html: str) -> int:
    """Highest ``?page=N`` in a MyBB thread's pagination block (>= 1).

    The collector walks pages 1..N. Reads the pagination anchors via the DOM and
    the ``page`` query param via urllib (URL parsing, not markup regex). A thread
    with no pagination block is a single page.
    """
    soup = BeautifulSoup(html, "html5lib")
    max_page = 1
    for anchor in soup.select("a.pagination_page, a.pagination_next, a.pagination_last"):
        href = str(anchor.get("href", ""))
        pages = parse_qs(urlparse(href).query).get("page", [])
        for value in pages:
            if value.isdigit():
                max_page = max(max_page, int(value))
    return max_page


def category_url(slug: str, page: int, *, by_created: bool = False) -> str:
    """Build a MyBB category-listing URL for ``page``.

    ``by_created`` sorts by thread CREATION date descending (``sortby=started``)
    instead of MyBB's default last-post order. Page 1 is spam-clogged on busy
    boards (exploit-ad copypasta self-bumps to the top under last-post sort), so
    a creation-date sort gives a deterministic chronological feed where fresh
    leaks stay on page 1..N instead of sinking. ``page<=1`` omits the page param.
    """
    params: list[str] = []
    if by_created:
        params += ["sortby=started", "order=desc"]
    if page > 1:
        params.append(f"page={page}")
    if not params:
        return slug
    sep = "&" if "?" in slug else "?"
    return f"{slug}{sep}{'&'.join(params)}"


def thread_page_url(url: str, page: int) -> str:
    """Page ``N`` of a MyBB thread given its page-1 URL (``?page=N`` query)."""
    if page <= 1:
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}page={page}"


__all__ = [
    "ParsedPost",
    "category_url",
    "parse_thread",
    "thread_page_count",
    "thread_page_url",
]
