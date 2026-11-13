"""thepress.co.nz — The Press (Christchurch, Stuff masthead). Added by
Arthur's word, 2026-11-13 ("Do it"): not on the estate's 87-source list; it
joins estate-news like every outlet.

Platform: Stuff's standalone masthead SPA (Angular shell, `data-theme` set
per masthead) — the article HTML carries NO body, no og: and no JSON-LD.
The SPA itself fetches the story JSON from the open same-origin API
`/api/v1.0/the-press/story/{id}` (id = the numeric segment of the article
URL); that API is the fetch path here, so the landed doc.url stays the
canonical article URL (unlike stuffconz's API-URL deviation). Piano paywall
gates some articles — the API serves what an anonymous reader sees and no
more; a stub lands as the stub, never past it (never-a-login rule; ruling
2026-11-13 keeps logins legal where we hold accounts — we hold none here).

Discovery: the Google News sitemap (recent window). ARCHIVE: the daily
sitemaps under /sitemap/{date}/sitemap.xml behind the sitemap index — the
on-site archive runs back to 2023-12-13 (measured 2026-11-13; older history
would be a Wayback route if ever asked). Robots: crawl allowed, no
Crawl-delay declared.

extract() parses the story JSON (stuffconz family): title = content.title,
body = paragraphs of content.contentBody.body, author = author[].name,
published = publishedDate, categories = section + topic names.
"""
from __future__ import annotations

import asyncio
import json
import re

from bs4 import BeautifulSoup

from . import base

SOURCE = "thepress.co.nz"
_BASE = "https://www.thepress.co.nz"
_API = _BASE + "/api/v1.0/the-press/story/"
_NEWS_SITEMAP = _BASE + "/sitemap/news/sitemap.xml"
_ID_RE = re.compile(r"/(\d{6,})/")

POLITE_SLEEP = 2.0
FETCH_CHUNK = 50
ARCHIVE = {"index": _BASE + "/sitemap/sitemap.xml",
           "article_re": r"/\d{6,}/", "polite": 2.0, "oldest_first": True}


async def discover(client) -> list[base.FeedItem]:
    xml = (await base.fetch(client, _NEWS_SITEMAP)).text
    items: list[base.FeedItem] = []
    for blk in re.findall(r"<url>(.*?)</url>", xml, re.S):
        loc = re.search(r"<loc>([^<]+)</loc>", blk)
        if not loc:
            continue
        pub = re.search(r"<news:publication_date>([^<]+)<", blk)
        published = None
        if pub:
            try:
                from datetime import datetime
                published = datetime.fromisoformat(pub.group(1).strip())
            except ValueError:
                published = None
        items.append(base.FeedItem(url=loc.group(1).strip(),
                                   published_at=published))
    return items


async def fetch_all(urls: list[str]) -> list[tuple[str, str]]:
    """run_source's fetch hook: story JSON per article URL (id from the URL),
    paced at POLITE_SLEEP. No login — what an anonymous reader sees."""
    out: list[tuple[str, str]] = []
    async with base.make_client() as client:
        for u in urls:
            m = _ID_RE.search(u)
            if not m:
                continue
            try:
                r = await base.fetch(client, _API + m.group(1))
                out.append((u, r.text))
            except Exception as e:  # noqa: BLE001
                print(f"  story fetch failed {u}: {type(e).__name__}: {e}")
            await asyncio.sleep(POLITE_SLEEP)
    return out


def extract(html: str, url: str):
    try:
        d = json.loads(html)
    except ValueError:
        return None                     # SPA shell or error page — not a story
    if not isinstance(d, dict):
        return None
    c = d.get("content") or {}
    title = ((c.get("title") or (d.get("teaser") or {}).get("title")) or "").strip()
    body_html = ((c.get("contentBody") or {}).get("body")) or ""
    soup = BeautifulSoup(body_html, "html.parser")
    parts = [t.get_text(" ", strip=True)
             for t in soup.find_all(["p", "h2", "h3", "li"])]
    text = base.clean_text(parts)
    if not title or not text:
        return None
    authors = ", ".join(a.get("name", "") for a in (d.get("author") or [])
                        if isinstance(a, dict) and a.get("name")) or None
    cats: list[str] = []
    if c.get("section"):
        cats.append(c["section"])
    for t in (c.get("topic") or []):
        if isinstance(t, dict) and t.get("name"):
            cats.append(t["name"])
    return base.Extracted(title=title, text=text, author=authors,
                          published_at=base._iso(d.get("publishedDate")),
                          categories=cats)
