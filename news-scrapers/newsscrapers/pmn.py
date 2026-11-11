"""pmn.co.nz — Pacific Media Network (Niu FM / 531pi / PMN): Pacific community
orgs, churches, trusts, Pasifika leaders and MPs — a register blind spot the
mainstream outlets miss.

Next.js App-Router SPA: the server HTML is an empty shell (article links and
bodies are client-rendered), so discovery AND every article go through the
headless browser (browserfetch), the same path as beehive. No robots.txt
exists (it falls through to the app shell), so nothing is disallowed.

Article URLs are /read/{section}/{slug} (three path segments). Title = og:title
and body = the densest paragraph block (genericrss handles both; the sidebars
use <a>, not <p>, so they don't win). There is no JSON-LD/meta date, so the
publication time is parsed from the visible "Published DD Month YYYY, h:mma"
line (NZ time).
"""
from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from . import base, genericrss

SOURCE = "pmn.co.nz"
_HOME = "https://www.pmn.co.nz/"
_NZ = ZoneInfo("Pacific/Auckland")
_PUB = re.compile(
    r"Published\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4}),?\s*(\d{1,2}):(\d{2})\s*([apAP][mM])")
_SETTLE_MS = 4000  # the /read/ body renders client-side ~3-4s after load


def _is_article(path: str) -> bool:
    segs = [s for s in path.split("/") if s]
    return len(segs) == 3 and segs[0] == "read"


async def discover(client) -> list[base.FeedItem]:
    from . import browserfetch
    pairs = await browserfetch.render_all([_HOME], settle_ms=_SETTLE_MS)
    if not pairs:
        return []
    soup = BeautifulSoup(pairs[0][1], "html.parser")
    seen: set[str] = set()
    items: list[base.FeedItem] = []
    for a in soup.select('a[href*="/read/"]'):
        href = urljoin(_HOME, (a.get("href") or "").split("?")[0].strip())
        if _is_article(urlparse(href).path) and href not in seen:
            seen.add(href)
            items.append(base.FeedItem(url=href))
    return items


async def fetch_all(urls: list[str]) -> list[tuple[str, str]]:
    """run_source's fetch hook — each article via the headless browser (the
    SPA shell has no body until JS renders it)."""
    from . import browserfetch
    return await browserfetch.render_all(urls, settle_ms=_SETTLE_MS)


def extract(html: str, url: str) -> base.Extracted | None:
    ex = genericrss.extract(html, url)   # og:title + densest-<p> body
    if ex is None:
        return None
    if ex.published_at is None:
        vis = " ".join(BeautifulSoup(html, "html.parser").get_text().split())
        m = _PUB.search(vis)
        if m:
            try:
                ex.published_at = datetime.strptime(
                    f"{m[1]} {m[2]} {m[3]} {m[4]}:{m[5]} {m[6].upper()}",
                    "%d %B %Y %I:%M %p").replace(tzinfo=_NZ)
            except ValueError:
                pass
    return ex
