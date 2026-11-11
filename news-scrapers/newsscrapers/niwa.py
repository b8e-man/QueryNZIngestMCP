"""niwa.co.nz — NIWA / Earth Sciences New Zealand (research-sector wave,
2026-07-25; post-merger the feed carries former-GNS territory too, which is
useful because gns.cri.nz itself is Imperva-walled).

The Drupal /rss.xml vanished in the Earth Sciences NZ replatform (404 by
2026-08-14) and no feed replaced it, so discovery walks the sitemap index
instead — same shape as the ODT walk, filtered to /news/ urls. Sitemap
lastmod is the only date the walk sees; genericrss.extract recovers the
real published date from the article's meta tags."""
from __future__ import annotations

import asyncio
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

from . import base, genericrss

SOURCE = "niwa.co.nz"
SITEMAP_INDEX = "https://niwa.co.nz/sitemap.xml"
_SM = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
_RECENT_DAYS = 21


def _lastmod(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def discover(client) -> list[base.FeedItem]:
    index = (await base.fetch(client, SITEMAP_INDEX)).text
    pages = [loc.text.strip()
             for loc in ET.fromstring(index.encode()).iter(_SM + "loc")
             if loc.text and loc.text.strip()]

    cutoff = datetime.now(timezone.utc) - timedelta(days=_RECENT_DAYS)
    items: list[base.FeedItem] = []
    for page in pages:
        await asyncio.sleep(base.POLITE_SLEEP)
        try:
            root = ET.fromstring((await base.fetch(client, page)).text.encode())
        except Exception as e:  # noqa: BLE001 — one sitemap page, not the walk
            print(f"  sitemap page error {page}: {type(e).__name__}: {e}")
            continue
        for u in root.iter(_SM + "url"):
            loc = (u.findtext(_SM + "loc") or "").strip()
            if "/news/" not in loc:
                continue
            lastmod = _lastmod(u.findtext(_SM + "lastmod"))
            if lastmod is None or lastmod < cutoff:
                continue
            items.append(base.FeedItem(url=loc, published_at=lastmod,
                                       category="news"))
    items.sort(key=lambda i: i.published_at or datetime.min.replace(
        tzinfo=timezone.utc), reverse=True)
    return items


extract = genericrss.extract
