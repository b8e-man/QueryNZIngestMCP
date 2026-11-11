"""nzier.org.nz — NZIER (research-sector wave, 2026-07-25). QSBO, OCR Shadow
Board, named economists. HubSpot CMS with a clean publications RSS. The real
body lives in the #hs_cos_wrapper_post_body rich-text span (genericrss's
heuristics instead land on sitewide .rtext__content footer boilerplate —
which is identical on every page, so the first seeding run hash-deduped 9 of
10 items into one junk row). Meta-description abstract is the fallback for
report-stub pages; the runner's 200-char floor still governs.

Archive: the RSS only carries recent items; the publications listing
paginates at /publications/page/N — walked by discover_archive (institute
backwalk, 2026-08-03). Dates are prose in .blog-infobar__date, not meta
tags; the old extract returned published_at=None on every article."""
from __future__ import annotations

from bs4 import BeautifulSoup

from . import base, genericrss

SOURCE = "nzier.org.nz"
_BASE = "https://www.nzier.org.nz"
discover = genericrss.make_discover(f"{_BASE}/publications/rss.xml")
discover_archive = genericrss.make_paged_listing_discover(
    lambda n: (f"{_BASE}/publications" if n == 0
               else f"{_BASE}/publications/page/{n + 1}"),
    r'href="(https://www\.nzier\.org\.nz/publications/[a-z0-9-]+)"', _BASE)


def extract(html: str, url: str) -> base.Extracted | None:
    soup = BeautifulSoup(html, "html.parser")
    og = soup.select_one('meta[property="og:title"]')
    title = " ".join((og.get("content") or "").split()) if og else ""
    if not title and soup.title:
        title = " ".join(soup.title.get_text().split())
    body = soup.select_one("#hs_cos_wrapper_post_body, .blog-body-1__content")
    paras = [" ".join(p.get_text().split())
             for p in (body.find_all(["p", "li"]) if body else [])]
    text = "\n\n".join(p for p in paras if p)
    if len(text) < 200:
        desc = soup.select_one('meta[name="description"]')
        if desc and desc.get("content"):
            text = " ".join(desc["content"].split())
    if not title or not text:
        return None
    infobar = soup.select_one(".blog-infobar__date")
    when = (genericrss.month_name_date(infobar.get_text(" ", strip=True))
            if infobar else None)
    return base.Extracted(title=title, text=text, author=None,
                          published_at=when, categories=[])
