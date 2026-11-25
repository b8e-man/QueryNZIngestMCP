"""worksafe.govt.nz — WorkSafe NZ media releases: prosecutions, enforceable
undertakings, sentencing — company names + directors, very register-dense.
Official source, open robots. RSS under /about-us/news-and-media/rss.

2026-11-25: the host now sits behind Incapsula — plain HTTP gets the
challenge stub on EVERY path (even robots.txt). Arthur ruled the browser
lane lift (2026-11-25, review 2026-11-26); the ecan recipe applies: one
solved browser session per fetch batch (feed and articles share the cookie —
separate sessions re-challenge)."""
from __future__ import annotations

from . import base, genericrss

SOURCE = "worksafe.govt.nz"
_FEED = "https://www.worksafe.govt.nz/about-us/news-and-media/rss"

extract = genericrss.extract

# fresh browser session every 5 urls: worksafe's challenge sets many cookies
# and the request API's cookie header overflows on long batches (measured
# 2026-11-25, "APIRequestContext.get: Parse Error: Header overflow")
FETCH_CHUNK = 5


async def discover(client) -> list[base.FeedItem]:
    from . import browserfetch
    pairs = await browserfetch.fetch_raw([_FEED], source=SOURCE)
    return genericrss.parse_feed(pairs[0][1]) if pairs else []


async def fetch_all(urls: list[str]) -> list[tuple[str, str]]:
    # DOM via render_all: the article body is JS-rendered — the raw server
    # response is an 843-byte shell with no text (measured 2026-11-25).
    # The FEED above stays on fetch_raw (raw XML; page.content() would give
    # Chromium's escaped XML-viewer output).
    from . import browserfetch
    return await browserfetch.render_all(urls, source=SOURCE)
