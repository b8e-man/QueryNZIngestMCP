"""Generic RSS scraper — RSS discovery + readability-style body extraction, for
the many WordPress/Ghost NZ outlets that expose a clean feed and don't need a
bespoke parser (source-expansion §9, 2026-07-16).

A source module is a three-liner:

    from . import genericrss
    SOURCE = "example.co.nz"
    discover = genericrss.make_discover("https://www.example.co.nz/feed")
    extract = genericrss.extract

Discovery is a dependency-free RSS regex (no lxml in the venv) that tolerates
CDATA and both RFC-822 and ISO pubDate. Extraction takes the article's <h1>
(or og:title) as the title and the densest direct-<p> container as the body —
robust across themes without per-site selectors. Sites whose markup needs
special handling get their own module (cf. alliedwp for tagDiv WP-REST).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from bs4 import BeautifulSoup

from . import base


def parse_feed(xml: str) -> list[base.FeedItem]:
    """RSS 2.0 / Atom items from feed text (regex, CDATA-tolerant) — usable on
    browser-rendered feeds too (ecan's feed is Incapsula'd; see ecan.py)."""
    items: list[base.FeedItem] = []
    for block in re.findall(r"<item[ >].*?</item>", xml, re.DOTALL) or \
                 re.findall(r"<entry[ >].*?</entry>", xml, re.DOTALL):  # RSS or Atom
        lm = re.search(r"<link[^>]*>(.*?)</link>", block, re.DOTALL) \
            or re.search(r'<link[^>]*href="([^"]+)"', block)
        url = re.sub(r"<!\[CDATA\[|\]\]>", "", (lm.group(1) if lm else "")).strip()
        if not url:
            continue
        tm = re.search(r"<title[^>]*>(.*?)</title>", block, re.DOTALL)
        pm = (re.search(r"<pubDate>(.*?)</pubDate>", block, re.DOTALL)
              or re.search(r"<published>(.*?)</published>", block, re.DOTALL)
              or re.search(r"<updated>(.*?)</updated>", block, re.DOTALL))
        title = re.sub(r"<!\[CDATA\[|\]\]>", "", tm.group(1)).strip() if tm else None
        items.append(base.FeedItem(
            url=url, title=title, published_at=_date(pm.group(1).strip() if pm else None)))
    return items


def make_discover(feed_url: str):
    async def discover(client) -> list[base.FeedItem]:
        xml = (await base.fetch(client, feed_url)).text
        return parse_feed(xml)
    return discover


def make_paged_listing_discover(page_url, link_re: str, url_base: str,
                                polite: float = 2.0, max_pages: int = 300):
    """ARCHIVE discovery for listing sources (institute backwalk, 2026-08-03):
    `page_url(n)` yields page 0, 1, 2… and the walk stops at the first page
    that contributes no NEW url (or errors — archives end with a 404 or an
    empty template, both read as 'done', never as a crash). Politeness
    between listing fetches is the module's own POLITE_SLEEP, passed in —
    the runner's sleep only covers article fetches."""
    import asyncio
    pat = re.compile(link_re)

    async def discover(client) -> list[base.FeedItem]:
        urls: list[str] = []
        for n in range(max_pages):
            try:
                html = (await base.fetch(client, page_url(n))).text
            except Exception:  # noqa: BLE001 — past the last page
                break
            before = len(urls)
            for m in pat.finditer(html):
                u = m.group(1) if m.groups() else m.group(0)
                u = u if u.startswith("http") else url_base + u
                if u not in urls:
                    urls.append(u)
            if len(urls) == before:
                break
            await asyncio.sleep(polite)
        return [base.FeedItem(url=u) for u in urls]
    return discover


def month_name_date(text: str) -> datetime | None:
    """'June 16, 2025' / '16 June 2025' -> aware datetime (institute sites
    write dates as prose, not meta tags)."""
    m = re.search(r"([A-Z][a-z]+) (\d{1,2}), (\d{4})", text or "")
    if not m:
        m = re.search(r"(\d{1,2}) ([A-Z][a-z]+) (\d{4})", text or "")
        if not m:
            return None
        day, month, year = m.group(1), m.group(2), m.group(3)
    else:
        month, day, year = m.group(1), m.group(2), m.group(3)
    try:
        return datetime.strptime(f"{day} {month} {year}", "%d %B %Y").replace(
            tzinfo=timezone.utc)
    except ValueError:
        return None


def make_listing_discover(listing_url: str, link_re: str, url_base: str):
    """Discovery for feedless sources with a server-rendered listing page:
    every href matching link_re becomes a FeedItem (dates come from the
    article pages at extract time; the runner's pre-fetch dedup keeps
    re-sweeps cheap). Research-sector wave, 2026-07-25."""
    pat = re.compile(link_re)

    async def discover(client) -> list[base.FeedItem]:
        html = (await base.fetch(client, listing_url)).text
        urls = []
        for m in pat.finditer(html):
            u = m.group(1) if m.groups() else m.group(0)
            u = u if u.startswith("http") else url_base + u
            if u not in urls:
                urls.append(u)
        return [base.FeedItem(url=u) for u in urls]
    return discover


def _date(s: str | None) -> datetime | None:
    if not s:
        return None
    dt = base._rfc2822(s) or base._iso(s)
    # the runner's since-cutoff is tz-aware; some feeds emit a tz-less pubDate
    # (naive) — assume UTC so the >= compare doesn't raise (farmersweekly).
    if dt is not None and dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _densest_body(soup: BeautifulSoup) -> str:
    best, best_len = "", 0
    for div in soup.find_all(["div", "article", "section"]):
        ps = div.find_all("p", recursive=False)
        if len(ps) < 3:
            continue
        parts = [" ".join(p.get_text().split()) for p in ps]
        joined = "\n\n".join(p for p in parts if p)
        if len(joined) > best_len:
            best, best_len = joined, len(joined)
    return best


def extract(html: str, url: str) -> base.Extracted | None:
    soup = BeautifulSoup(html, "html.parser")
    # prefer og:title — the canonical article title; a bare first-<h1> often
    # catches a site banner ("Support the Guardian")
    og = soup.select_one('meta[property="og:title"]')
    title_el = soup.select_one("article h1, h1.entry-title, h1.post-title, h1")
    title = ((og.get("content").strip() if og and og.get("content") else "")
             or (" ".join(title_el.get_text().split()) if title_el else ""))
    # prefer common article-body wrappers, else the densest paragraph block
    body_el = soup.select_one(
        "article .entry-content, .post-content, .article-content, .gh-content, "
        ".article-body, .story-content, .article-detail, article .content")
    text = ""
    if body_el is not None:
        paras = [" ".join(p.get_text().split()) for p in body_el.find_all("p")]
        text = "\n\n".join(p for p in paras if p)
    if len(text) < 200:
        # select_one takes the FIRST wrapper match, which can be an empty
        # decoy (stoppress has a bare .post-content before the real body) —
        # the densest direct-<p> block is the reliable fallback.
        text = max((text, _densest_body(soup)), key=len)
    if not title or len(text) < 200:
        return None
    meta = soup.select_one('meta[property="article:published_time"]')
    published = base._iso(meta.get("content")) if meta and meta.get("content") else None
    if published is None:  # JSON-LD fallback (SilverStripe/Crux emit only this)
        jm = re.search(r'"datePublished"\s*:\s*"([^"]+)"', html)
        if jm:
            published = base._iso(jm.group(1))
    return base.Extracted(title=title, text=text, author=None,
                          published_at=published, categories=[])


# ── B11 ruling 28 (2026-08-24): historical DEPTH via the site's own sitemap
# index. Walks <sitemapindex> → each <urlset>, yields dated FeedItems, and
# supports RESUME: the walk runs oldest-first over the sub-sitemaps and a
# `progress` callback receives each sub-sitemap url after it is fully
# yielded, so backwalk can persist "done through here" and a later run
# starts after it. Listing fetches pace at the module's politeness.
_LOC = re.compile(r"<loc>\s*(?:<!\[CDATA\[)?\s*(.*?)\s*(?:\]\]>)?\s*</loc>", re.S)
_URL_BLOCK = re.compile(r"<url>(.*?)</url>", re.S)
_LASTMOD = re.compile(r"<lastmod>\s*([^<\s]+)")


def parse_sitemap_index(xml: str) -> list[tuple[str, str | None]]:
    """[(sub-sitemap url, lastmod)] in document order (empty for a urlset)."""
    if "<sitemapindex" not in xml[:4000].lower():
        return []
    out = []
    for block in re.findall(r"<sitemap>(.*?)</sitemap>", xml, re.S):
        loc = _LOC.search(block)
        if not loc:
            continue
        lm = _LASTMOD.search(block)
        out.append((loc.group(1).strip(), lm.group(1)[:10] if lm else None))
    return out


def parse_urlset(xml: str, article_re: str | None = None) -> list[base.FeedItem]:
    """Dated FeedItems from a <urlset>; `article_re` keeps article URLs only."""
    pat = re.compile(article_re) if article_re else None
    items = []
    for block in _URL_BLOCK.findall(xml):
        loc = _LOC.search(block)
        if not loc:
            continue
        u = loc.group(1).strip()
        if pat and not pat.search(u):
            continue
        lm = _LASTMOD.search(block)
        items.append(base.FeedItem(url=u, published_at=_date(lm.group(1)) if lm else None))
    return items


def make_sitemap_archive_discover(index_url, article_re: str | None = None, *,
                                  sitemap_re: str | None = None,
                                  polite: float = 2.0, oldest_first: bool = True,
                                  skip_done=None, progress=None, max_sitemaps: int | None = None,
                                  census=None):
    """discover_archive for a sitemap-index source. `index_url` is one index
    URL or a LIST of them (NZME publishes one Arc index per masthead — the
    sub-sitemap URLs are distinct per masthead, so one resume `done` set spans
    all of them). `sitemap_re` keeps only matching sub-sitemaps (WordPress
    indexes mix post-/page-/tag- sitemaps); `skip_done(url) -> bool` skips
    sub-sitemaps a previous run completed; `progress(url)` is called after each
    sub-sitemap's items are collected (persist it to resume).

    `census(total, remaining)` is called ONCE per discover, with the index's
    whole sub-sitemap count and how many this run still had to walk. C313
    (2026-10-06): the index already knew the denominator and threw it away, so
    the lane could report "4,314 sub-sitemaps already done" and never "of how
    many" — an open-ended walk nobody could put a date on. A count without its
    population is the shape that lesson "a gate proves nothing until you know
    what it ENUMERATED" names."""
    import asyncio
    spat = re.compile(sitemap_re) if sitemap_re else None
    index_urls = [index_url] if isinstance(index_url, str) else list(index_url)

    async def discover(client) -> list[base.FeedItem]:
        subs: list[tuple[str, str | None]] = []
        plain: list[base.FeedItem] = []
        for iu in index_urls:
            try:
                xml = (await base.fetch(client, iu)).text
            except Exception as e:  # noqa: BLE001 — one dead index must not end the walk
                print(f"  index error {iu}: {type(e).__name__}: {e}")
                continue
            these = parse_sitemap_index(xml)
            if spat:
                these = [x for x in these if spat.search(x[0])]
            if not these:                               # a plain urlset: one page, no resume
                plain += parse_urlset(xml, article_re)
            else:
                subs += these
        if not subs:
            return plain
        if oldest_first:
            # a date embedded in the sub-sitemap URL (Arc's /sitemap/YYYY-MM-DD/)
            # is the true age key; <lastmod> is uniform (when the feed rebuilt),
            # so fall back to it only when the URL carries no date.
            def _age(s):
                m = re.search(r"/(\d{4}-\d{2}-\d{2})/", s[0])
                return (m.group(1) if m else (s[1] or "0000"), s[0])
            subs = sorted(subs, key=_age)
        if census:
            # before the walk, so it is reported even when max_sitemaps stops
            # this run early — the denominator is a property of the INDEX, not
            # of how much of it we got through today
            census(len(subs), sum(1 for s, _ in subs if not (skip_done and skip_done(s))))
        items: list[base.FeedItem] = []
        walked = 0
        for sub, _lm in subs:
            if skip_done and skip_done(sub):
                continue
            if max_sitemaps is not None and walked >= max_sitemaps:
                break
            await asyncio.sleep(polite)
            try:
                sx = (await base.fetch(client, sub)).text
            except Exception as e:  # noqa: BLE001 — one dead sub-sitemap must not end the walk
                print(f"  sitemap error {sub}: {type(e).__name__}: {e}")
                continue
            items += parse_urlset(sx, article_re)
            walked += 1
            if progress:
                # report the CUMULATIVE discovered count so the caller can mark
                # done only sub-sitemaps fully inside its fetch limit — a sub-
                # sitemap whose cumulative count exceeds the limit was tail-cut
                # by run_source's items[:limit] and must NOT be marked done
                # (else its articles are skip_done forever — silent archive loss).
                progress(sub, len(items))
        return items + plain
    return discover
