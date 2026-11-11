"""Arc/Fusion news-sitemap discovery — for Arc Publishing sites (1News, Te Ao
Māori News) that expose article URLs via `/arc/outboundfeeds/...sitemap...`
rather than RSS. Body extraction reuses genericrss.extract (Arc renders the
article into `.article-body` with og:title, which that handles).

Handles both Arc sitemap shapes: one-level (the sitemap already lists dated
article URLs, e.g. Te Ao) and two-level (an index of sub-sitemaps, e.g. 1News)
— a shallow recursive collector walks either. Dated-path filter
(/YYYY/MM/DD/) keeps sections/tags out.
"""
from __future__ import annotations

import re

from . import base, genericrss

_ARTICLE = re.compile(r"https?://[^\s<]+/\d{4}/\d{2}/\d{2}/[^\s<]+")


async def _collect(client, sitemap_url: str, depth: int = 0) -> list[str]:
    try:
        xml = (await base.fetch(client, sitemap_url)).text
    except Exception as e:  # noqa: BLE001
        print(f"  arc sitemap error {sitemap_url}: {type(e).__name__}: {e}")
        return []
    locs = re.findall(r"<loc>\s*(.*?)\s*</loc>", xml, re.DOTALL)
    articles = [u for u in locs if _ARTICLE.match(u.strip())]
    if articles:
        return [u.strip() for u in articles]
    if depth == 0:                       # these are sub-sitemaps — one level down
        out: list[str] = []
        for sm in locs[:8]:
            out += await _collect(client, sm.strip(), depth=1)
        return out
    return []


def make_discover(sitemap_url: str):
    async def discover(client) -> list[base.FeedItem]:
        urls = await _collect(client, sitemap_url)
        seen: set[str] = set()
        items: list[base.FeedItem] = []
        for u in urls:
            if u in seen:
                continue
            seen.add(u)
            items.append(base.FeedItem(url=u))     # date/title come from the page at extract
        return items
    return discover


extract = genericrss.extract
