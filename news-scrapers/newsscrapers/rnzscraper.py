"""rnz.co.nz (Radio New Zealand) — port of the Java RNZ scraper
(ops/scraper-service-standalone .../scraper/rnzscraper/).

Discovery: the same five topic RSS feeds as RnzRssScraper. Content parsing
follows RnzContentScraper's multi-layout selectors, extended for the current
(2026) Tailwind layout (article[data-testid=newsArticle], paragraphs in
div.font-serif-text — the Java selector required .leading-relaxed which the
live site no longer uses):
  title    h1.c-story-header__headline / article h1
  content  div.article__body p / article div.font-serif-text p /
           div.article__body
  date     div.c-dateblock span.updated / article time — prefer the ISO
           datetime attribute (new layout), else Java's text parsing
           ("on " prefix stripped; d MMMM yyyy / d/M/yyyy;
           Australia/Sydney, kept as-is from the Java code)
  author   span.author-name a / the Java layout-2 span (usually absent —
           most RNZ stories carry no byline)

Categories deviation: Java tagged articles with the feed name from RSS
metadata, but base.run_source only lands extract()'s categories, so we derive
them from the URL path instead (/news/<category>/<id>/<slug> → <category>),
which is finer-grained than the feed name (e.g. "community", "regional").
Content is paragraph-joined via base.clean_text ("\n\n") instead of Jsoup's
single text() blob (house style for the ports).
"""
from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from . import base

SOURCE = "rnz.co.nz"
FEEDS = [
    "https://www.rnz.co.nz/rss/national.xml",
    "https://www.rnz.co.nz/rss/political.xml",
    "https://www.rnz.co.nz/rss/business.xml",
    "https://www.rnz.co.nz/rss/world.xml",
    "https://www.rnz.co.nz/rss/sport.xml",
]

_AUS = ZoneInfo("Australia/Sydney")  # kept from RnzContentScraper

_TITLE_SELS = ("h1.c-story-header__headline",
               "article[data-testid='lifeArticle'] h1",
               "article h1")
_CONTENT_SELS = ("div.article__body p",
                 "article div.font-serif-text p",   # current Tailwind layout
                 "div.article__body")
_DATE_SELS = ("div.c-dateblock span.updated", "article time")
_AUTHOR_SELS = ("span.author-name a",
                "article div.text-foreground-secondary.text-sm "
                "div.text-foreground-primary span")


def _text(el) -> str:
    """Jsoup Element.text() equivalent: whitespace-collapsed, trimmed."""
    return " ".join(el.get_text().split()) if el is not None else ""


def _parse_date_text(date_text: str) -> datetime | None:
    """Port of RnzContentScraper.parseDate (text-based fallback)."""
    cleaned = date_text.partition("on ")[2] or date_text.partition(" ")[2] \
        or date_text
    cleaned = cleaned.strip()
    if "/" in cleaned:
        try:  # d/M/yyyy
            return datetime.strptime(cleaned, "%d/%m/%Y").replace(tzinfo=_AUS)
        except ValueError:
            pass
    for fmt in ("%d %B %Y", "%d %b %Y"):
        for candidate in (cleaned, date_text.strip()):
            try:
                return datetime.strptime(candidate, fmt).replace(tzinfo=_AUS)
            except ValueError:
                continue
    return None


def _categories_from_url(url: str) -> list[str]:
    """/news/<category>/<id>/<slug> → ["<category>"] (see docstring)."""
    segs = [s for s in urlsplit(url).path.split("/") if s]
    cats: list[str] = []
    for seg in segs:
        if re.fullmatch(r"\d+", seg):
            break
        if seg != "news":
            cats.append(seg)
    return cats


def extract(html: str, url: str) -> base.Extracted | None:
    soup = BeautifulSoup(html, "html.parser")

    title = ""
    for sel in _TITLE_SELS:
        title = _text(soup.select_one(sel))
        if title:
            break

    parts: list[str] = []
    for sel in _CONTENT_SELS:
        parts = [_text(p) for p in soup.select(sel)]
        if any(parts):
            break
    text = base.clean_text(parts)
    if not text:
        return None

    published_at = None
    for sel in _DATE_SELS:
        el = soup.select_one(sel)
        if el is None:
            continue
        iso = (el.get("datetime") or "").strip()
        if iso:
            try:
                published_at = datetime.fromisoformat(iso.replace("Z", "+00:00"))
                break
            except ValueError:
                pass
        date_text = _text(el)
        if date_text:
            published_at = _parse_date_text(date_text)
            if published_at:
                break

    author = None
    for sel in _AUTHOR_SELS:
        author = _text(soup.select_one(sel)) or None
        if author:
            break

    return base.Extracted(title=title, text=text, author=author,
                          published_at=published_at,
                          categories=_categories_from_url(url))
