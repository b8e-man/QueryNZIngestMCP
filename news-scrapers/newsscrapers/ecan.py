"""ecan.govt.nz — Environment Canterbury news releases (councils sweep
2026-07-17: of 16 probed, only ECan exposed a feed). 2026-11-09: the host now
sits behind Incapsula — plain HTTP, proxied or not, gets the 205-byte
_Incapsula_Resource stub (the beehive class: the residential IP alone is not
enough, a real browser auto-solves the challenge). browserfetch.fetch_raw
gives raw bodies in ONE solved session (feed and articles share the cookie —
separate sessions re-challenge). Note: Chromium's XML viewer escapes a feed
into <pre> text, so page.content() is useless for the feed — the raw body is
the real RSS."""
from __future__ import annotations

from . import base, genericrss

SOURCE = "ecan.govt.nz"
_FEED = "https://www.ecan.govt.nz/news/rss"

extract = genericrss.extract


async def discover(client) -> list[base.FeedItem]:
    from . import browserfetch
    pairs = await browserfetch.fetch_raw([_FEED], source=SOURCE)
    return genericrss.parse_feed(pairs[0][1]) if pairs else []


async def fetch_all(urls: list[str]) -> list[tuple[str, str]]:
    from . import browserfetch
    return await browserfetch.fetch_raw(urls, source=SOURCE)
