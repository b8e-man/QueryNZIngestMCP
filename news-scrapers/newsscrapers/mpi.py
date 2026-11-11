"""mpi.govt.nz — Ministry for Primary Industries media releases: biosecurity
prosecutions, fisheries enforcement, food recalls, forestry/ETS — fines and
company names throughout. Official source, open robots (CMS internals only).
The site serves a ~1KB JS stub to plain clients, so BOTH discovery and article
fetch render through the headless browser (same shape as pmn). Links on the
rendered listing are full URLs under /news/media-releases/{slug}."""
from __future__ import annotations

import re

from . import base, genericrss

SOURCE = "mpi.govt.nz"
_LIST = "https://www.mpi.govt.nz/news/media-releases/"
_ART = re.compile(r"https://www\.mpi\.govt\.nz/news/media-releases/[a-z0-9-]{10,}")
_SETTLE_MS = 4000


async def discover(client) -> list[base.FeedItem]:
    from . import browserfetch
    pairs = await browserfetch.render_all([_LIST], settle_ms=_SETTLE_MS)
    if not pairs:
        return []
    urls = sorted(set(_ART.findall(pairs[0][1])))
    return [base.FeedItem(url=u) for u in urls]


async def fetch_all(urls: list[str]) -> list[tuple[str, str]]:
    from . import browserfetch
    return await browserfetch.render_all(urls, settle_ms=_SETTLE_MS)


extract = genericrss.extract
