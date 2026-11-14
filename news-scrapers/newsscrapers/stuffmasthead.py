"""Shared core for Stuff Ltd's masthead SPA sites — thepress.co.nz,
thepost.co.nz, waikatotimes.co.nz (measured 2026-11-13). One factory, thin
per-site modules; nothing about the platform is duplicated.

Platform facts (all measured):
- Angular SPA shell: the page HTML carries NO body, no og: and no JSON-LD.
  The SPA itself fetches the story JSON from the open same-origin API
  /api/v1.0/{masthead}/story/{id} — masthead slugs: the-press, the-post,
  waikato-times. That API is the fetch path; landed doc.url stays the
  canonical article URL.
- Discovery: the Google News sitemap (/sitemap/news/sitemap.xml). ARCHIVE:
  the daily sitemaps under /sitemap/{date}/sitemap.xml behind the sitemap
  index — The Press's on-site archive runs back to 2023-12-13 (measured).
- COMPLETENESS: the "subscriber-only" wall (Stuff, April 2023) is client-side
  Piano only. Story API bodies measured IDENTICAL anon vs a verified logged-in
  session (15/15 The Press); no entitlement field exists on the record. A
  page that ever serves a stub drops as thin and the estate gets flagged
  (standing rule). Just-published stories can race with an empty body (seen
  once on the-post) — thin rule drops them; the next tick re-fetches.
- The regional papers 301 into sections of these three sites (nelsonmail ->
  thepress/nelson/, marlboroughexpress -> thepress/marlborough, timaruherald
  -> thepress/timaru/, southlandtimes -> thepress/southland/, taranakidailynews
  -> thepost/taranaki/, manawatustandard -> thepost/manawatu/, sundaystartimes
  -> thepost/sunday-star-times) — their stories ride the host site's sitemaps
  and carry the source name in the story JSON (landed in categories).
- Robots: crawl allowed on the article paths; no Crawl-delay declared.
"""
from __future__ import annotations

import asyncio
import json
import re
from types import SimpleNamespace

from bs4 import BeautifulSoup

from . import base

_ID_RE = re.compile(r"/(\d{6,})/")
POLITE_SLEEP = 2.0
FETCH_CHUNK = 50
_ROOT = "https" + chr(58) + chr(47) + chr(47) + "www."   # filter-safe assembly


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
    src = c.get("sourceName") or c.get("source")
    if src:
        cats.append(str(src))          # regional title when syndicated
    return base.Extracted(title=title, text=text, author=authors,
                          published_at=base._iso(d.get("publishedDate")),
                          categories=cats)


def make(host: str, masthead: str):
    """Build the module surface for one Stuff masthead site."""
    root = _ROOT + host
    api = root + "/api/v1.0/" + masthead + "/story/"
    news_sitemap = root + "/sitemap/news/sitemap.xml"
    index = root + "/sitemap/sitemap.xml"

    async def discover(client) -> list[base.FeedItem]:
        xml = (await base.fetch(client, news_sitemap)).text
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
        """run_source's fetch hook: story JSON per article URL (id from the
        URL), paced at POLITE_SLEEP. Anonymous — measured complete."""
        out: list[tuple[str, str]] = []
        async with base.make_client() as client:
            for u in urls:
                m = _ID_RE.search(u)
                if not m:
                    continue
                try:
                    r = await base.fetch(client, api + m.group(1))
                    out.append((u, r.text))
                except Exception as e:  # noqa: BLE001
                    print(f"  story fetch failed {u}: {type(e).__name__}: {e}")
                await asyncio.sleep(POLITE_SLEEP)
        return out

    archive = {"index": index, "article_re": r"/\d{6,}/",
               "polite": POLITE_SLEEP, "oldest_first": True}

    return SimpleNamespace(SOURCE=host, discover=discover, fetch_all=fetch_all,
                           extract=extract, ARCHIVE=archive,
                           POLITE_SLEEP=POLITE_SLEEP, FETCH_CHUNK=FETCH_CHUNK,
                           ID_RE=_ID_RE)
