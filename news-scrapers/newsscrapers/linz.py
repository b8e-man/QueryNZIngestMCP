"""linz.govt.nz — Land Information NZ news: overseas-investment decisions,
Crown land, place naming, survey system — land-entity relevant. Official
source, open robots, Drupal server-rendered. Discovery scrapes the /news index
for /news/YYYY-MM/{slug} links; plain fetch. (No date meta on articles — the
landed date stays null rather than guessing from the month path.)"""
from __future__ import annotations

import re
from urllib.parse import urljoin

from . import base, genericrss

SOURCE = "linz.govt.nz"
_LIST = "https://www.linz.govt.nz/news"
_ART = re.compile(r"/news/\d{4}-\d{2}/[a-z0-9-]{6,}")


async def discover(client) -> list[base.FeedItem]:
    html = (await base.fetch(client, _LIST)).text
    urls = sorted({urljoin(_LIST, m) for m in _ART.findall(html)}, reverse=True)
    return [base.FeedItem(url=u) for u in urls]


extract = genericrss.extract
