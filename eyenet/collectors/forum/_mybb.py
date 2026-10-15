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
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from bs4.element import Tag

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
# darkforums renders day-first, 2-digit year ("06-09-26"); raidforums renders
# US month-first, 4-digit year ("11-29-2023"). Both are MyBB — the format is a
# per-board locale setting, not an engine difference. Tried in order; the 2-digit
# vs 4-digit year keeps them unambiguous (one fails ValueError, the other parses).
_DATE_FMTS = ("%d-%m-%y, %I:%M %p", "%m-%d-%Y, %I:%M %p")
# The DATE half alone (no time). A "Yesterday" / "Today" post renders the absolute
# DATE in the tooltip title and the TIME as trailing text; this parses the title
# date so it can be recombined with that time. Also the last-resort for a genuinely
# date-only stamp (-> midnight), still a real date, never a now() substitution.
_DATE_ONLY_FMTS = ("%d-%m-%y", "%m-%d-%Y")
_TIME_FMT = "%I:%M %p"  # the time tail shared by "Today,"/"Yesterday," forms
# The "01:40 PM" time tail, pulled out of a "Yesterday, 01:40 PM" rendering to
# recombine with the tooltip's absolute date.
_TIME_RE = re.compile(r"(\d{1,2}:\d{2}\s*[AP]M)", re.IGNORECASE)
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

    Absolute (`_DATE_FMTS`, darkforums DD-MM-YY + raidforums MM-DD-YYYY) first, then
    the relative renderings ("Today, HH:MM AM/PM", "Yesterday, ...", "N minutes/hours/
    days ago", "an hour ago"). A relative parse yields a REAL timestamp (not a
    now()-substitution), so the collector's recency guard stays quiet. `now` is
    injectable for tests; defaults to the board-local naive clock to match `_DATE_FMTS`.
    """
    raw = raw.strip()
    for fmt in _DATE_FMTS:
        try:
            return datetime.strptime(raw, fmt)  # noqa: DTZ007 - board-local naive, see module note
        except ValueError:
            continue
    ref = now or datetime.now()  # noqa: DTZ005 - board-local naive, matches _DATE_FMTS
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


def _parse_date_only(raw: str) -> datetime | None:
    """Parse a bare DATE (no time) to midnight, or None. Last resort before fault."""
    raw = raw.strip()
    for fmt in _DATE_ONLY_FMTS:
        try:
            return datetime.strptime(raw, fmt)  # noqa: DTZ007 - board-local naive
        except ValueError:
            continue
    return None


def _post_date_text(date_span: Tag) -> str:
    """Visible text of ``span.post_date`` MINUS the trailing ``post_edit`` note.

    The edit note ("(This post was last modified: ...)") lives in a nested
    ``span.post_edit`` and would otherwise pollute the date string.
    """
    parts: list[str] = []
    for child in date_span.children:
        if isinstance(child, Tag):
            cls = child.get("class")
            classes = cls.split() if isinstance(cls, str) else list(cls or [])
            if "post_edit" in classes:
                continue
            text = child.get_text()
        else:
            text = str(child)
        if text.strip():
            parts.append(text.strip())
    return " ".join(parts).replace(" ,", ",").strip()


def _extract_post_datetime(date_span: Tag) -> tuple[str, datetime | None]:
    """Resolve ``span.post_date`` to (raw, datetime) across darkforums' layouts.

    Three renderings, all handled, preferring an EXACT absolute timestamp:
    - direct text ``06-09-26, 10:56 PM`` (older posts)
    - nested tooltip holding the full timestamp: ``<span title="29-09-26,
      01:24 AM">4 hours ago</span>`` (recent posts) -> use the title
    - split "Yesterday"/"Today": ``<span title="05-10-26">Yesterday</span>,
      01:40 PM`` -> the tooltip has the DATE, the trailing text the TIME; recombine
      them into ``05-10-26, 01:40 PM`` rather than losing the time to a fault.

    Returns (raw, None) only when nothing yields a real date — the caller then
    fails closed (no now() substitution).
    """
    titled = date_span.select_one("span[title]")
    title = str(titled.get("title", "")).strip() if titled else ""
    full = _post_date_text(date_span)  # e.g. "Yesterday, 01:40 PM" / "06-09-26, 10:56 PM"

    # 1. Tooltip is itself a full absolute timestamp (recent-post layout).
    if title:
        dt = _parse_date(title)
        if dt is not None:
            return title, dt
    # 2. Tooltip is a bare DATE and the visible text carries the TIME: recombine.
    tm = _TIME_RE.search(full)
    if title and tm and _parse_date_only(title) is not None:
        combined = f"{title}, {tm.group(1)}"
        dt = _parse_date(combined)
        if dt is not None:
            return combined, dt
    # 3. The visible text parses on its own (direct absolute, or relative "N ago").
    if full:
        dt = _parse_date(full)
        if dt is not None:
            return full, dt
    # 4. Date-only last resort (-> midnight): a real date beats a now() lie.
    for cand in (title, full):
        if cand:
            dt = _parse_date_only(cand)
            if dt is not None:
                return cand, dt
    return (title or full), None


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

        # Date rendering varies by post age on darkforums: older posts carry the
        # Date rendering varies by post age (direct text / nested-tooltip /
        # split "Yesterday, HH:MM"); _extract_post_datetime handles all three and
        # returns (raw, None) only when nothing is a real date (caller fails closed).
        date_span = container.select_one("span.post_date")
        posted_raw, posted_at = _extract_post_datetime(date_span) if date_span else ("", None)

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
        # OWN words only: _extract_body_text strips MyBB quote blocks (someone
        # else's content) and expands auto-link hrefs (so a truncated display URL
        # keeps its full target). Without the quote strip, a one-word reply quoting
        # a breach dump gets tagged as a breach dump.
        body_text = _extract_body_text(body) if body is not None else ""

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


def _expand_link_hrefs(node: Tag) -> None:
    """Replace each auto-linkified URL's visible text with its ``href``.

    MyBB renders a long link with TRUNCATED display text
    (``http://nanrwa6b4z7vo5hxi64faaidcomwylxlb...uqd.onion``) while the FULL URL
    lives in the ``href``. ``get_text()`` would keep the elided display and throw
    the real target away — silently mangling onions, paste URLs and every long
    link. Rewrite each ``a.mycode_url`` anchor's text to its href so the full URL
    survives into ``body_text``. Only auto-links are touched (their text IS the
    URL); quote/profile/mention anchors are left alone. ``body_html`` is captured
    before this runs, so the evidence-faithful HTML keeps the original markup."""
    for anchor in node.select("a.mycode_url[href]"):
        href = str(anchor.get("href", "")).strip()
        if href:
            anchor.string = href


def _extract_body_text(body: Tag) -> str:
    """The poster's own words from a ``post_body`` node: drop quote blocks
    (someone else's content), expand auto-link hrefs (recover truncated URLs),
    then flatten to text. Shared by live parsing and the body-repair backfill."""
    for quote in body.select("blockquote.mycode_quote"):
        quote.decompose()
    _expand_link_hrefs(body)
    return body.get_text("\n", strip=True)


def body_text_from_html(body_html: str) -> str:
    """Re-derive ``body_text`` from a stored ``body_html`` fragment — the repair
    path for posts collected before :func:`_extract_body_text` expanded hrefs.
    The stored HTML already has CF emails decoded and keeps quote blocks, so this
    mirrors the live extraction exactly."""
    soup = BeautifulSoup(body_html, "html5lib")
    return _extract_body_text(soup)


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
    """Highest ``page=N`` in a MyBB pagination block (>= 1).

    The collector walks pages 1..N. The page number is pulled from each pagination
    anchor's href with a regex rather than ``parse_qs`` + ``isdigit``, because
    raidforums.im's SEO rewrite emits a MALFORMED double-query when a sort is
    applied (``Forum-Databases?page=205?sortby=started``): parse_qs then yields the
    value ``"205?sortby=started"``, which ``isdigit()`` rejects, collapsing a
    205-page forum to one page. The regex reads the digits after ``page=`` in any
    of ``?page=N`` / ``&page=N`` / the malformed ``?page=N?...`` forms. A block with
    no pagination anchors is a single page.
    """
    soup = BeautifulSoup(html, "html5lib")
    max_page = 1
    for anchor in soup.select("a.pagination_page, a.pagination_next, a.pagination_last"):
        m = re.search(r"[?&]page=(\d+)", str(anchor.get("href", "")))
        if m:
            max_page = max(max_page, int(m.group(1)))
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


# A logged-in MyBB page carries a logout link (member.php?action=logout) and the
# User CP; a guest page has neither.
_LOGGED_IN_MARKERS = ("action=logout", "usercp")


def is_logged_in(html: str) -> bool:
    """True if the session jar is still authenticated on this MyBB board."""
    body = html.lower()
    return any(marker in body for marker in _LOGGED_IN_MARKERS)


def thread_key_from_url(url: str) -> str:
    """MyBB ``Thread-<slug>--<tid>`` -> ``<tid>``; fall back to the slug.

    URL-derived fallback key, used only when a thread page yields no canonical
    tid. The caller still normalizes the slug for move-dedup.
    """
    slug = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
    if "--" in slug:
        tail = slug.rsplit("--", 1)[-1]
        if tail.isdigit():
            return tail
    return slug


__all__ = [
    "ParsedPost",
    "category_url",
    "is_logged_in",
    "parse_thread",
    "thread_key_from_url",
    "thread_page_count",
    "thread_page_url",
]
