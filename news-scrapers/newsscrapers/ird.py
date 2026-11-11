"""ird.govt.nz — Inland Revenue media releases: tax prosecutions, fraud
sentencings, compliance campaigns — person+company dense. Official source,
open robots. Sitecore, server-rendered: discovery scrapes the media-releases
index for /media-releases/{year}/{slug} links; plain fetch."""
from __future__ import annotations

import re
from urllib.parse import urljoin

from . import base, genericrss

SOURCE = "ird.govt.nz"
_LIST = "https://www.ird.govt.nz/media-releases"
_ART = re.compile(r"/media-releases/\d{4}/[a-z0-9-]{8,}")


async def discover(client) -> list[base.FeedItem]:
    html = (await base.fetch(client, _LIST)).text
    urls = sorted({urljoin(_LIST, m) for m in _ART.findall(html)}, reverse=True)
    return [base.FeedItem(url=u) for u in urls]


extract = genericrss.extract
