"""crux.org.nz — Crux (Queenstown/Central Otago investigative): council
finances, fast-track mining, district-council stories — dense with register
entities. SilverStripe, no RSS. Its sitemap 429s on a full walk and buries
recent stories among 2018 pages, so discovery scrapes the homepage instead
(~90 recent `/crux-news/{slug}/` links). Fully-open robots. Body + date via
genericrss (.article-content + JSON-LD datePublished)."""
from __future__ import annotations

import re

from . import base, genericrss

SOURCE = "crux.org.nz"
_HOME = "https://crux.org.nz"
# article = /{section}/{slug}/ ; drop the nav/utility sections
_LINK = re.compile(r"/(?:crux-news|news|business|environment|health|sport|opinion)/[a-z0-9][a-z0-9-]+/")


async def discover(client) -> list[base.FeedItem]:
    home = (await base.fetch(client, _HOME + "/")).text
    urls = {(_HOME + m if m.startswith("/") else m) for m in _LINK.findall(home)}
    return [base.FeedItem(url=u) for u in sorted(urls)]


# Crux's JSON-LD datePublished is WRONG on some articles (2026-07-20: a March
# article carried "2026-10-01"; 59 of 70 held rows had no date at all). The
# VISIBLE header date ("Mar 01, 2026" — first occurrence, before the
# .post-date sidebar entries) is authoritative — parse that instead.
_HDR_DATE = re.compile(
    r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\.?\s+(\d{1,2}),\s+(\d{4})")
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}


def extract(html: str, url: str):
    ex = genericrss.extract(html, url)
    if ex is None:
        return None
    m = _HDR_DATE.search(html)
    if m:
        from datetime import date
        try:
            ex.published_at = date(int(m.group(3)), _MONTHS[m.group(1)], int(m.group(2)))
        except (ValueError, KeyError):
            pass
    return ex
