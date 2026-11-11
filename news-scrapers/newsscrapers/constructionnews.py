"""constructionnews.co.nz — NZ Construction News (WordPress; trade-press wave
tier 1, 2026-07-25). Projects and contractor entities the mainstream press
only covers at failure time. Canonical host is apex (www 301s to bare domain).
robots: standard WP (wp-admin only). Generic RSS."""
from __future__ import annotations
import html
from . import genericrss
SOURCE = "constructionnews.co.nz"
_rss = genericrss.make_discover("https://constructionnews.co.nz/feed/")


async def discover(client):
    # this feed appends ?utm_source=rss… (with entity-encoded &#038;) to every
    # link — strip the query so the URL-hash dedup key is stable
    items = await _rss(client)
    for i in items:
        i.url = html.unescape(i.url).split("?")[0]
    return items

extract = genericrss.extract
