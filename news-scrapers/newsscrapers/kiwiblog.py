"""kiwiblog.co.nz — port of the Java Kiwiblog scraper
(ops/scraper-service-standalone .../scraper/kiwiblog/).

Discovery: single RSS feed (KiwiblogRssScraper). Content parsing follows
KiwiblogContentScraper: article.post container; title from
".post-header h2.title, h1.title"; date + author parsed out of the postmeta
line ("July 7, 2026 3:00pm by David Farrar", Pacific/Auckland); content is
the text of ".content p" joined with single spaces (Jsoup Elements.text()
shape — matches the golden fixtures, deliberately NOT \n\n-joined).
Categories come from RSS only in the Java design, so extract() returns none.
The Java proxy-rotation layer is not ported (direct connection path only).
"""
from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from . import base

SOURCE = "kiwiblog.co.nz"
FEEDS = ["https://www.kiwiblog.co.nz/feed"]

_NZ = ZoneInfo("Pacific/Auckland")
_META_DATE_RE = re.compile(r"(\w+ \d+, \d{4} \d+:\d+[ap]m)")


def _text(el) -> str:
    """Jsoup Element.text() equivalent: whitespace-collapsed, trimmed."""
    return " ".join(el.get_text().split()) if el is not None else ""


def extract(html: str, url: str) -> base.Extracted | None:
    soup = BeautifulSoup(html, "html.parser")
    for br in soup.find_all("br"):
        br.replace_with("\n")

    article = soup.select_one("article.post")
    if article is None:
        return None

    title = _text(article.select_one(".post-header h2.title, .post-header h1.title, h1.title"))
    postmeta = _text(article.select_one(".post-header div.postmeta"))

    published_at = None
    m = _META_DATE_RE.search(postmeta)
    if m:
        try:
            published_at = datetime.strptime(
                m.group(1), "%B %d, %Y %I:%M%p").replace(tzinfo=_NZ)
        except ValueError:
            published_at = None

    # Java: article.select(".content p").text() — space-joined paragraph blob
    paras = [_text(p) for p in article.select(".content p")]
    text = " ".join(p for p in paras if p)

    author = postmeta.split("by ", 1)[1].strip() if "by " in postmeta else ""

    return base.Extracted(title=title, text=text, author=author or None,
                          published_at=published_at, categories=[])


# B11 ruling 28 (2026-08-24, ARCHIVE_SURVEY_2026-08-24): 65 sub-sitemaps (CDATA locs); corpus already deep — fills recent gaps only.
# Walked by newsscrapers.backwalk (resumable, oldest sub-sitemap first).
ARCHIVE = {
    "index": "https://www.kiwiblog.co.nz/sitemap.xml",
    "sitemap_re": r"/post-sitemap",
}
