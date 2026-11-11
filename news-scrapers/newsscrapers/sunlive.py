"""sunlive.co.nz — SunLive (Sun Media): Tauranga / Bay of Plenty free daily —
a coverage hole the national outlets miss. No RSS and no sitemap, so discovery
scrapes article links off the homepage and its section-index pages. robots
allows the general agent (only named AI-training crawlers are blocked; we do
inference-time extraction, not training).

Article URLs are `/news/{id}-{slug}.html`; section-index pages are
`/news/{n}_{n}_{name}.html` — the discover walk fetches those for breadth.
No og:title (a bare <h1> is the comment count), so the title comes from the
<title> tag; body is `.article-content`; date is article:published_time.
"""
from __future__ import annotations

import asyncio
import re

from bs4 import BeautifulSoup

from . import base

SOURCE = "sunlive.co.nz"
_HOME = "https://www.sunlive.co.nz"
_ARTICLE = re.compile(r"/news/\d+-[^\"'#?]+\.html")
_SECTION = re.compile(r"/news/\d+_\d+_[^\"'#?]+\.html")
_TITLE_STRIP = re.compile(r"^SunLive\s*[-–]\s*|\s*[-–]\s*The Bay's News First\s*$")


def _abs(path: str) -> str:
    return path if path.startswith("http") else _HOME + path


async def discover(client) -> list[base.FeedItem]:
    home = (await base.fetch(client, _HOME + "/")).text
    arts: set[str] = {_abs(m) for m in _ARTICLE.findall(home)}
    sections = {_abs(m) for m in _SECTION.findall(home)}
    for sec in list(sections)[:12]:
        try:
            page = (await base.fetch(client, sec)).text
        except Exception as e:  # noqa: BLE001
            print(f"  sunlive section error {sec}: {type(e).__name__}: {e}")
            continue
        arts |= {_abs(m) for m in _ARTICLE.findall(page)}
        await asyncio.sleep(0.3)

    def _id(u: str) -> int:  # /news/{id}-… — higher id = more recent
        m = re.search(r"/news/(\d+)-", u)
        return int(m.group(1)) if m else 0
    return [base.FeedItem(url=u) for u in sorted(arts, key=_id, reverse=True)]


def extract(html: str, url: str) -> base.Extracted | None:
    soup = BeautifulSoup(html, "html.parser")
    title = _TITLE_STRIP.sub("", " ".join(soup.title.get_text().split())) if soup.title else ""
    body_el = soup.select_one(".article-content, article .article-content")
    if body_el is None:
        return None
    paras = [" ".join(p.get_text().split()) for p in body_el.find_all("p")]
    text = "\n\n".join(p for p in paras if p)
    if not title or len(text) < 200:
        return None
    meta = soup.select_one('meta[property="article:published_time"]')
    published = base._iso(meta.get("content")) if meta and meta.get("content") else None
    return base.Extracted(title=title, text=text, author=None,
                          published_at=published, categories=[])
