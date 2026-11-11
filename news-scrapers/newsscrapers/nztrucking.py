"""nztrucking.co.nz — NZ Trucking magazine (trade-press wave tier 2,
2026-07-25): the transport-press slot. Operator, fleet, and freight-company
entities. WordPress, but every feed URL serves the homepage HTML (feeds
disabled), so discovery walks the NEWEST Yoast post-sitemap instead —
chronologically ascending with lastmod stamps, so the tail is the fresh end.
Extraction is genericrss (article:published_time present) with the
" - NZ Trucking" og:title suffix stripped. Yoast robots allow-all."""
from __future__ import annotations

import re

from . import base, genericrss

SOURCE = "nztrucking.co.nz"
_HOME = "https://www.nztrucking.co.nz"
_SITEMAP = re.compile(r"<loc>(https://www\.nztrucking\.co\.nz/post-sitemap\d*\.xml)</loc>")
_ENTRY = re.compile(r"<loc>([^<]+)</loc>\s*<lastmod>([^<]+)</lastmod>")
_SUFFIX = re.compile(r"\s*[-–]\s*NZ Trucking\s*$")


async def discover(client) -> list[base.FeedItem]:
    index = (await base.fetch(client, _HOME + "/sitemap_index.xml")).text
    maps = _SITEMAP.findall(index)
    if not maps:
        return []
    posts = (await base.fetch(client, maps[-1])).text
    items = []
    for url, lastmod in _ENTRY.findall(posts)[-60:]:     # fresh tail
        items.append(base.FeedItem(url=url, published_at=base._iso(lastmod)))
    items.reverse()                                       # newest first
    return items


def extract(html: str, url: str) -> base.Extracted | None:
    ex = genericrss.extract(html, url)
    if ex is not None:
        ex.title = _SUFFIX.sub("", ex.title.replace("\xa0", " ")).strip()
    return ex


# B11 ruling 28 (2026-08-24, ARCHIVE_SURVEY_2026-08-24): 22 sub-sitemaps back to 2019.
# Walked by newsscrapers.backwalk (resumable, oldest sub-sitemap first).
ARCHIVE = {
    "index": "https://www.nztrucking.co.nz/sitemap_index.xml",
    "sitemap_re": r"/post-sitemap",
}
