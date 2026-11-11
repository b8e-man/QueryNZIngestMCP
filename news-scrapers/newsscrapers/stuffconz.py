"""stuff.co.nz — port of the Java Stuff scraper
(ops/scraper-service-standalone .../scraper/stuffconz/).

Discovery: Atom feed https://www.stuff.co.nz/rss (StuffRssScraper). Content:
Stuff article pages are a client-rendered React app — the HTML carries no
article body, and the site bot-walls many fetches with HTTP 410 — so, exactly
like StuffContentScraper, the body comes from the internal JSON API
https://www.stuff.co.nz/api/v1.0/stuff/story/{id}. Because base.run_source
fetches FeedItem.url and hands the response body to extract(), discover()
maps each feed entry to its API URL (deviation: the landed doc.url is the API
URL; the canonical URL lives in the payload at content.url).

extract() therefore parses the API JSON, not HTML (the golden fixtures are
API payloads too): title = content.title, text = content.intro + "\n\n" +
Jsoup-style text() of content.contentBody.body, author = author[0].name
(fallback: byline), publishedAt = ISO publishedDate, categories = canonical
URL path segments before the numeric article id
(StuffSitemapParser.ArticleLink.extractCategoriesFromUrl).

The Java daily-sitemap track (historical backfill from 2015) is intentionally
not ported — these ports are the fresh-news path.
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime

from bs4 import BeautifulSoup, Comment, Declaration, Doctype, NavigableString
from bs4 import ProcessingInstruction, Tag

from . import base

SOURCE = "stuff.co.nz"
FEEDS = ["https://www.stuff.co.nz/rss"]

API_BASE = "https://www.stuff.co.nz/api/v1.0/stuff/story/"

# Jsoup's block-level tags (Tag.java) — used to reproduce Element.text()
# spacing, since the golden content is Jsoup's single-space-joined text blob.
_BLOCK = frozenset(
    """html body frameset script noscript style meta link title frame noframes
    section nav aside hgroup header footer p h1 h2 h3 h4 h5 h6 ul ol pre div
    blockquote hr address figure figcaption form fieldset ins del dl dt dd li
    table caption thead tfoot tbody colgroup col tr th td video audio canvas
    details menu plaintext template article main svg math center dir applet
    marquee listing""".split())
_SKIP = frozenset({"script", "style"})
_NON_TEXT = (Comment, Declaration, Doctype, ProcessingInstruction)


def _jsoup_text(fragment_html: str) -> str:
    """Equivalent of Jsoup Element.text(): whitespace-normalised, with a
    single space injected at block/br boundaries."""
    soup = BeautifulSoup(fragment_html, "html.parser")
    buf: list[str] = []

    def last_ws() -> bool:
        return bool(buf) and buf[-1].endswith(" ")

    def walk(node) -> None:
        for child in node.children:
            if isinstance(child, _NON_TEXT):
                continue
            if isinstance(child, NavigableString):
                s = re.sub(r"\s+", " ", str(child))
                if s.startswith(" ") and last_ws():
                    s = s[1:]
                if s:
                    buf.append(s)
            elif isinstance(child, Tag):
                if child.name in _SKIP:
                    continue
                if ((child.name in _BLOCK or child.name == "br")
                        and buf and not last_ws()):
                    buf.append(" ")
                walk(child)
                if (child.name in _BLOCK and not last_ws()
                        and isinstance(child.next_sibling, NavigableString)):
                    buf.append(" ")

    walk(soup)
    return "".join(buf).strip()


def _article_id(url: str) -> str | None:
    """First all-numeric path segment (StuffContentScraper.extractArticleId)."""
    path = re.sub(r"^https?://[^/]+/", "", url or "")
    for part in path.split("/"):
        if part.isdigit():
            return part
    return None


def _categories_from_url(url: str) -> list[str]:
    """Path segments before the numeric article id
    (StuffSitemapParser.ArticleLink.extractCategoriesFromUrl)."""
    path = re.sub(r"^https?://[^/]+/", "", url or "")
    if "https://www.stuff.co.nz" in path:
        return []
    cats: list[str] = []
    for part in path.split("/"):
        if not part:
            continue
        if part.isdigit():
            break
        cats.append(part)
    return cats


def _iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


async def discover(client) -> list[base.FeedItem]:
    """Feed entries mapped to their internal-API URLs (see module docstring)."""
    items: list[base.FeedItem] = []
    for feed in FEEDS:
        try:
            entries = base.parse_rss((await base.fetch(client, feed)).text)
        except Exception as e:  # noqa: BLE001
            print(f"  feed error {feed}: {type(e).__name__}: {e}")
            continue
        for it in entries:
            aid = _article_id(it.url)
            if aid:
                items.append(base.FeedItem(url=API_BASE + aid, title=it.title,
                                           published_at=it.published_at))
        await asyncio.sleep(base.POLITE_SLEEP)
    return items


def extract(html: str, url: str) -> base.Extracted | None:
    """Parse a story-API JSON payload (mirrors parseApiResponse)."""
    try:
        root = json.loads(html)
    except (ValueError, TypeError):
        return None  # not an API payload (e.g. the bot-wall HTML page)
    if not isinstance(root, dict):
        return None

    content_node = root.get("content") or {}
    title = (content_node.get("title") or "").strip()
    intro = (content_node.get("intro") or "").strip()
    html_body = ((content_node.get("contentBody") or {}).get("body")) or ""

    body_text = _jsoup_text(html_body) if html_body else ""
    text = base.clean_text([intro, body_text])
    if not text:
        return None

    author = None
    authors = root.get("author")
    if isinstance(authors, list) and authors:
        author = (authors[0] or {}).get("name") or None
    else:
        byline = root.get("byline")
        if byline and byline != "null":
            author = byline

    # categories come from the canonical article URL — recover it from the
    # payload when we were handed the API URL by run_source
    canonical = url if "/api/" not in url else (content_node.get("url") or "")
    return base.Extracted(title=title, text=text, author=author,
                          published_at=_iso(root.get("publishedDate")),
                          categories=_categories_from_url(canonical))
