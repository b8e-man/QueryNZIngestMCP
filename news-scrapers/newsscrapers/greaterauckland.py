"""greaterauckland.org.nz — Greater Auckland: transport/urban policy analysis,
agency- and project-dense. robots blocks named AI/search bots but the general
agent is Allow: /. WordPress feed.

2026-11-09: article pages 403 this runtime (plain and browser UA — measured,
diagnosed once) while the FEED serves FULL articles (content:encoded 14–33 KB,
73 <p> in the first item) and /wp-json answers. So the lane reads article
content from the feed — one request per sweep, zero article fetches — and
falls back to wp-json-by-slug for URLs the feed no longer carries (backwalk's
archive discover swaps this module's discover, so _CONTENT stays empty there
and every URL takes the fallback, paced at POLITE_SLEEP per robots)."""
from __future__ import annotations

import asyncio
import html as _html
import re
from xml.etree import ElementTree as ET

from . import base, genericrss

SOURCE = "greaterauckland.org.nz"
FEED = "https://www.greaterauckland.org.nz/feed/"
WPJSON = "https://www.greaterauckland.org.nz/wp-json/wp/v2/posts"
_CONTENT_NS = "{http://purl.org/rss/1.0/modules/content/}encoded"

_CONTENT: dict[str, tuple[str, str]] = {}  # url -> (title, content html) from the feed
FETCH_CHUNK = 10  # bounds the wp-json fallback batches (C215 chunking)

extract = genericrss.extract


def _wrap(url: str, title: str, content_html: str) -> str:
    """Feed content arrives as a bare fragment; og:title carries the title and
    the entry-content wrapper is the shape genericrss.extract expects."""
    return (f'<html><head><meta property="og:title" '
            f'content="{_html.escape(title, quote=True)}"></head>'
            f'<body><article><div class="entry-content">{content_html}'
            f'</div></article></body></html>')


async def discover(client) -> list[base.FeedItem]:
    r = await base.fetch(client, FEED)
    items = base.parse_rss(r.text)
    root = ET.fromstring(r.text.encode())
    for it in root.iter("item"):
        link = (it.findtext("link") or "").strip()
        body = it.findtext(_CONTENT_NS) or ""
        if link and body:
            _CONTENT[link] = ((it.findtext("title") or "").strip(), body)
    return items


async def fetch_all(urls: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    todo: list[str] = []
    for u in urls:
        if u in _CONTENT:
            title, body = _CONTENT[u]
            out[u] = _wrap(u, title, body)
        else:
            todo.append(u)
    if todo:
        async with base.make_client() as c:
            for u in todo:
                await asyncio.sleep(POLITE_SLEEP)
                try:
                    r = await base.fetch(c, WPJSON,
                                         params={"slug": u.rstrip("/").split("/")[-1]})
                    posts = r.json()
                    if posts:
                        p = posts[0]
                        title = re.sub(r"<[^>]+>", "", p["title"]["rendered"])
                        out[u] = _wrap(u, title, p["content"]["rendered"])
                except Exception as e:  # noqa: BLE001
                    print(f"  wp-json miss {u}: {type(e).__name__}: {e}")
    return out


# B11 ruling 28 (2026-08-24, ARCHIVE_SURVEY_2026-08-24): 38 sub-sitemaps back to 2011; robots Crawl-delay 30.
# Walked by newsscrapers.backwalk (resumable, oldest sub-sitemap first).
ARCHIVE = {
    "index": "https://www.greaterauckland.org.nz/sitemap.xml",
    "sitemap_re": r"/post-sitemap",
    "polite": 30.0,
}
POLITE_SLEEP = 30.0   # robots Crawl-delay — binds the wp-json fallback too
