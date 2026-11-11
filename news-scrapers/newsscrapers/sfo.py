"""sfo.govt.nz — Serious Fraud Office media releases: fraud/corruption
prosecutions, guilty pleas, sentencings — maximum register density per word.
Official source, open robots (CMS internals only). Names charged persons:
capture rides the news path; person-link DISPLAY is governed by the compliance
gates.

2026-11-09: the headless render of the media-releases LISTING is CHALLENGED
(2/2 measured) while the pages themselves are server-rendered and answer 200
to plain fetch — honest UA included. The browser requirement was stale.
Discovery now walks the SilverStripe site-tree sitemap (538 media-release
urls enumerated 2026-11-09); articles fetch plain like any news source."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from . import base, genericrss

SOURCE = "sfo.govt.nz"
_SITEMAP_INDEX = "https://www.sfo.govt.nz/sitemap.xml"
_ART = r"/media-cases/media-releases/[a-z0-9-]{8,}"

extract = genericrss.extract


async def discover(client) -> list[base.FeedItem]:
    items: list[base.FeedItem] = []
    index = (await base.fetch(client, _SITEMAP_INDEX)).text
    subs = [u for u, _lm in genericrss.parse_sitemap_index(index)]
    for sub in subs:
        try:
            xml = (await base.fetch(client, sub)).text
        except Exception as e:  # noqa: BLE001 — one dead sub-sitemap must not end the walk
            print(f"  sitemap error {sub}: {type(e).__name__}: {e}")
            continue
        items += genericrss.parse_urlset(xml, _ART)
        await asyncio.sleep(base.POLITE_SLEEP)
    # newest first so run_source's limit keeps the most recent releases
    items.sort(key=lambda i: i.published_at or datetime.min.replace(
        tzinfo=timezone.utc), reverse=True)
    return items
