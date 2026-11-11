"""thespinoff.co.nz — port of the Java Spinoff scraper
(ops/scraper-service-standalone .../scraper/spinoff/).

Discovery: sitemap-based, as in the Java design (The Spinoff has no feed in
the original pipeline). discover() fetches the sitemap index, keeps the
monthly "/posts/yyyy-MM.xml" child sitemaps, and reads the newest
_MONTHS_TO_SCAN of them (recency filtering happens in base.run_source).

Content parsing follows SpinoffContentScraper: per-page layout detection —
".spinoff-logo .hidden-screen" present -> V1 selectors, absent -> V2 legacy
selectors — with the same content fallbacks (article, div[class*=content],
main). Deviation from Java: content is paragraph-joined via base.clean_text
(\n\n) instead of Jsoup's single text() blob. Category = first URL path
segment; date from meta/ISO, "MMMM d, yyyy", or the dd-MM-yyyy URL segment.
"""
from __future__ import annotations

import asyncio
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from . import base

SOURCE = "thespinoff.co.nz"
FEEDS: list[str] = []  # discovery is sitemap-based — see discover()

SITEMAP_INDEX = "https://thespinoff.co.nz/sitemap.xml"
_MONTHS_TO_SCAN = 2
_SM = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
_NZ = ZoneInfo("Pacific/Auckland")

_V1 = ("div.layout-article-header h1", 'meta[property="article:published_time"]',
       ".article-content", ".byline .name a")
_V2 = (".coverstory-postinfo h1", '.coverstory-postinfo [itemprop="date"]',
       ".cover-story", 'a[rel="author"]')


def _text(el) -> str:
    """Jsoup Element.text() equivalent: whitespace-collapsed, trimmed."""
    return " ".join(el.get_text().split()) if el is not None else ""


def _lastmod(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    # sitemap lastmod may be a bare date — keep run_source's recency
    # comparison (tz-aware) happy
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def discover(client) -> list[base.FeedItem]:
    """Sitemap index -> newest /sitemaps/articles/N.xml pages -> article urls.
    (2026-11-09 redesign: the monthly /posts sitemaps are gone; article sitemaps
    are numbered, 1 = newest, so sort ascending by index and take the first
    _MONTHS_TO_SCAN pages.)"""
    index = (await base.fetch(client, SITEMAP_INDEX)).text
    monthly = sorted(
        (loc.text.strip() for loc in ET.fromstring(index.encode()).iter(_SM + "loc")
         if loc.text and "/sitemaps/articles/" in loc.text),
        key=lambda u: int(u.rsplit("/", 1)[-1].split(".")[0]))[:_MONTHS_TO_SCAN]

    items: list[base.FeedItem] = []
    for sm_url in monthly:
        await asyncio.sleep(base.POLITE_SLEEP)
        try:
            root = ET.fromstring((await base.fetch(client, sm_url)).text.encode())
        except Exception as e:  # noqa: BLE001
            print(f"  sitemap error {sm_url}: {type(e).__name__}: {e}")
            continue
        for u in root.iter(_SM + "url"):
            loc = (u.findtext(_SM + "loc") or "").strip()
            if loc:
                items.append(base.FeedItem(
                    url=loc, published_at=_lastmod(u.findtext(_SM + "lastmod"))))
    # newest first so run_source's limit keeps the most recent articles
    items.sort(key=lambda i: i.published_at or datetime.min.replace(
        tzinfo=timezone.utc), reverse=True)
    return items


def _parse_date(s: str, url: str) -> datetime | None:
    s = (s or "").strip()
    if s:
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            pass
        try:
            return datetime.strptime(s, "%B %d, %Y").replace(tzinfo=_NZ)
        except ValueError:
            pass
    try:  # e.g. /politics/12-07-2026/slug
        seg = urlsplit(url).path.strip("/").split("/")[1]
        return datetime.strptime(seg, "%d-%m-%Y").replace(tzinfo=_NZ)
    except (IndexError, ValueError):
        return None


def extract(html: str, url: str) -> base.Extracted | None:
    soup = BeautifulSoup(html, "html.parser")
    for br in soup.find_all("br"):
        br.replace_with("\n")

    title_sel, date_sel, content_sel, author_sel = (
        _V1 if soup.select_one(".spinoff-logo .hidden-screen") is not None else _V2)

    title = _text(soup.select_one(title_sel))
    if not title:
        og = soup.select_one('meta[property="og:title"]')
        title = (og.get("content") or "").strip() if og else ""

    date_text = ""
    for el in soup.select(date_sel):
        date_text = (el.get("datetime") or el.get("content") or _text(el)).strip()
        if date_text:
            break
    published_at = _parse_date(date_text, url)

    content_el = soup.select_one(content_sel)
    for fb in ("article", "div[class*=content]", "main"):
        if content_el is not None:
            break
        content_el = soup.select_one(fb)
    if content_el is None:
        return None

    parts = [_text(p) for p in content_el.find_all(["p", "h2", "h3"])]
    text = base.clean_text(parts) or _text(content_el)
    if not text:
        return None

    author = _text(soup.select_one(author_sel)) or None
    segs = urlsplit(url).path.strip("/").split("/")
    categories = [segs[0]] if segs and segs[0] else []

    return base.Extracted(title=title, text=text, author=author,
                          published_at=published_at, categories=categories)
