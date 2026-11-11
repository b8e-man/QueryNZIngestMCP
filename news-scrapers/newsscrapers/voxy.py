"""voxy.co.nz — Voxy: press-release wire aggregator. High overlap with Scoop,
but the content-hash dedup collapses duplicates, so it's cheap breadth. robots
Allow: /. No feed — discovery scrapes /{section}/{slug} links off the homepage
(crux-style); body via genericrss densest-paragraph."""
from __future__ import annotations

import re

from . import base, genericrss

SOURCE = "voxy.co.nz"
_HOME = "https://www.voxy.co.nz"
# article = /{section}/{long-slug}; drop author/tag/utility paths
_LINK = re.compile(r"/(?!author/|tag/|about|contact|search)[a-z-]+/[a-z0-9][a-z0-9-]{13,}")


async def discover(client) -> list[base.FeedItem]:
    home = (await base.fetch(client, _HOME + "/")).text
    urls = {(_HOME + m if m.startswith("/") else m) for m in _LINK.findall(home)}
    return [base.FeedItem(url=u) for u in sorted(urls)]


extract = genericrss.extract
