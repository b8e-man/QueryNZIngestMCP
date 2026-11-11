"""Allied Media regional WordPress sites — shared scraper (2026-07-16 audit).

The Allied ecosystem audit (ideas: capture every masthead) resolved to:
  * most mastheads redirect INTO odt.co.nz sections → already covered by the
    ODT sitemap walk (The Star, Mountain Scene, Oamaru Mail, The News,
    Clutha Leader, Ensign, Southland Express, Wanaka Sun, …);
  * two live standalone WordPress sites (tagDiv "Newspaper" theme, open WP
    REST API, robots allow):
      - greystar.co.nz        (Greymouth Star + Hokitika Guardian +
                               West Coast Messenger — both redirect here)
      - ashburtoncourier.co.nz (retired 2026-08-14 — folded into odt.co.nz)
  * dropped: blenheimsun.co.nz (static shell around a weekly PDF e-edition),
    kaikourastar.co.nz (parked "future website"), cromwellbulletin.co.nz
    (dormant — one 2022 "Hello world!"; Cromwell news rides odt.co.nz),
    thecourier.co.nz / northcanterburynews.co.nz (no site).

Discovery: the WP REST posts API (exact dates, no HTML parsing). Extraction:
tagDiv markup — h1.entry-title / h1.tdb-title-text + .td-post-content p,
published from the article:published_time meta.
"""
from __future__ import annotations

import json

from bs4 import BeautifulSoup

from . import base


def make_discover(api_root: str):
    """WP REST discovery for one site: newest 50 posts with links + dates."""
    async def discover(client) -> list[base.FeedItem]:
        url = (f"{api_root}/wp-json/wp/v2/posts"
               f"?per_page=50&orderby=date&order=desc&_fields=link,date_gmt,title")
        posts = json.loads((await base.fetch(client, url)).text)
        items: list[base.FeedItem] = []
        for p in posts if isinstance(posts, list) else []:
            link = p.get("link")
            if not link:
                continue
            items.append(base.FeedItem(
                url=link,
                title=(p.get("title") or {}).get("rendered"),
                published_at=base._iso((p.get("date_gmt") or "") + "+00:00"),
            ))
        return items
    return discover


def extract(html: str, url: str) -> base.Extracted | None:
    soup = BeautifulSoup(html, "html.parser")
    title_el = soup.select_one("h1.entry-title, h1.tdb-title-text")
    content = soup.select_one(".td-post-content, .tdb-block-inner .td-post-content, article .entry-content")
    if title_el is None or content is None:
        return None
    title = " ".join(title_el.get_text().split())
    paras = [" ".join(p.get_text().split()) for p in content.select("p")]
    text = "\n\n".join(p for p in paras if p)
    meta = soup.select_one('meta[property="article:published_time"]')
    published = base._iso(meta.get("content")) if meta and meta.get("content") else None
    author_el = soup.select_one(".tdb-author-name, .td-post-author-name a, a[rel='author']")
    author = " ".join(author_el.get_text().split()) if author_el else None
    if not title or not text:
        return None
    return base.Extracted(title=title, text=text, author=author,
                          published_at=published, categories=[])
