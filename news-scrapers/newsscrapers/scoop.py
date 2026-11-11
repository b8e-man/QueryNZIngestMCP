"""scoop.co.nz — port of the Java Scoop scraper
(ops/scraper-service-standalone .../scraper/scoop/).

Discovery: the 9 topic RSS feeds from ScoopRssScraper. The Java sitemap track
(per-year .xml.gz archives, month-precision dates) is NOT ported — RSS covers
the fresh-news path this framework serves.

Content parsing follows ScoopContentScraper: two page layouts with selector
fallbacks; <ul>/<ol> rendered as "• item" lines; blocks joined with blank
lines. The golden fixtures for this source contain the Java rawHtml fragment
(the chosen content elements) rather than a full page, so extract() falls back
to treating the document's top-level non-div elements as the content when no
#article/#contentwrap container exists — title/author are not derivable from
those fixtures (Java merged them from RSS metadata).
"""
from __future__ import annotations

import email.utils
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from . import base

SOURCE = "scoop.co.nz"
FEEDS = [f"http://www.scoop.co.nz/storyindex/index.rss?s.c={code}"
         for code in ("BU", "SC", "PA", "PO", "AK", "WO", "CU", "ED", "GE")]

_NZ = ZoneInfo("Pacific/Auckland")
# Java ScoopHelper.DATE_FORMATTERS, minus the zoned duplicates strptime covers.
_LOCAL_FORMATS = ("%A, %d %B %Y, %I:%M %p", "%Y-%m-%d", "%b %d, %Y")


def _text(el) -> str:
    """Jsoup Element.text() equivalent: whitespace-collapsed, trimmed."""
    return " ".join(el.get_text().split()) if el is not None else ""


def _parse_date(s: str) -> datetime | None:
    if not s:
        return None
    # Java normalises am/pm -> AM/PM before parsing (strptime doesn't care,
    # kept for parity with the documented flow).
    s = re.sub(r"(?i)\bam\b", "AM", re.sub(r"(?i)\bpm\b", "PM", s.strip()))
    try:
        return email.utils.parsedate_to_datetime(s)          # RFC 1123 / 2822
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))  # ISO offset
    except ValueError:
        pass
    for fmt in _LOCAL_FORMATS:
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=_NZ)
        except ValueError:
            continue
    return None


def extract(html: str, url: str) -> base.Extracted | None:
    soup = BeautifulSoup(html, "html.parser")
    for br in soup.find_all("br"):
        br.replace_with("\n")

    # -- title: #article layout -> legacy #contentwrap -> meta[name=title]
    title = _text(soup.select_one("#article .story-top h1"))
    if not title:
        title = _text(soup.select_one("#contentwrap .entrytitle"))
    if not title:
        meta = soup.select_one("meta[name=title]")
        title = (meta.get("content") or "").strip() if meta else ""

    # -- date: byline <b> -> .entrymeta1 own text
    date_text = _text(soup.select_one("#article span.byline b"))
    if not date_text:
        alt = soup.select_one("#contentwrap .entrymeta1")
        if alt is not None:  # ownText(): direct text nodes only
            date_text = " ".join(
                " ".join(s.split())
                for s in alt.find_all(string=True, recursive=False)).strip()
    published_at = _parse_date(date_text)

    # -- content: direct children of the article container, divs excluded
    chosen = soup.select("#article > *:not(div)")
    if not chosen:
        chosen = soup.select("#contentwrap .entrybody > *:not(div)")
    if not chosen and soup.find("html") is None:
        # rawHtml fragment (golden fixtures): the fragment IS the chosen set
        chosen = [el for el in soup.find_all(recursive=False)
                  if el.name not in ("div", "script", "style")]
    if not chosen:
        return None

    parts: list[str] = []
    for el in chosen:
        if el.name in ("ul", "ol"):
            parts.append("\n".join("• " + _text(li) for li in el.find_all("li")))
        elif el.name in ("script", "style"):
            continue
        else:
            parts.append(_text(el))
    text = base.clean_text(parts)
    if not text:
        return None

    author = _text(soup.select_one("#article span.byline > b a")) or None

    categories: list[str] = []
    seen: set[str] = set()
    for a in soup.select("#bread-crumb > a"):
        c = _text(a)
        if c and c.lower() != "scoop" and c.lower() not in seen:
            seen.add(c.lower())
            categories.append(c)

    return base.Extracted(title=title, text=text, author=author,
                          published_at=published_at, categories=categories)
