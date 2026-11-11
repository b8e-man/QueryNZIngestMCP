"""Config-driven HTML decision-corpus scraper — the genericrss sibling for
official bodies that publish decisions / case notes / rulings as HTML pages
(not PDFs, not feeds): Privacy Commissioner case notes, LINZ OIO decision
summaries, and the long tail the accountability-body census surfaces.

A source module stays a few lines:

    from . import htmlsource
    SOURCE = "privacy.org.nz"
    POLITE_SLEEP = 11.0                      # robots crawl-delay 10
    discover = htmlsource.make_discover(
        listings=[...listing URLs...],
        link_re=r'href="(/resources-and-learning/case-notes[^"]+)"',
        url_base="https://www.privacy.org.nz")
    extract = htmlsource.make_extract(category="decision")

Rides the whole newsscrapers stack: base.run_source politeness + ledger dedup
+ land_document, the registry go/no-go board, and the Flow surfaces. The
`category` lands in articles.categories so decision corpora are queryable
apart from news prose (and the v3 extractor can grow genre rules for them
the way it did for 'document').

Back-catalogue depth: modules build their listing list with `paged()`; the
HTMLSOURCE_PAGES env var (default 1 = incremental front page) deepens every
paged listing at cluster time without touching code.
"""
from __future__ import annotations

import os
import re

from bs4 import BeautifulSoup

from . import base, genericrss


def pages() -> int:
    try:
        return max(1, int(os.environ.get("HTMLSOURCE_PAGES", "1")))
    except ValueError:
        return 1


def paged(template: str, step: int = 1, start: int = 0) -> list[str]:
    """Expand a listing template with {n} into HTMLSOURCE_PAGES many URLs.
    step: the page-param increment (20 for ?start= offsets, 1 for ?page=)."""
    return [template.format(n=start + i * step) for i in range(pages())]


def make_sitemap_discover(sitemap_url: str, include_re: str, child_cap: int = 6):
    """Sitemap-diff discovery for sources whose listing pages are JS-only but
    whose sitemap.xml enumerates every detail URL (RBNZ Coveo listings, SFO
    SilverStripe). Handles one level of <sitemapindex> nesting. The runner's
    ledger dedup turns the full-history sitemap into an incremental feed."""
    inc = re.compile(include_re)

    async def discover(client) -> list[base.FeedItem]:
        xml = (await base.fetch(client, sitemap_url)).text
        if "<sitemapindex" in xml:
            children = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml)[:child_cap]
            parts = []
            for cu in children:
                try:
                    parts.append((await base.fetch(client, cu)).text)
                except Exception:  # noqa: BLE001
                    continue
            xml = "\n".join(parts)
        urls = []
        for loc in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml):
            if inc.search(loc) and loc not in urls:
                urls.append(loc)
        return [base.FeedItem(url=u) for u in urls]
    return discover


def make_discover(listings: list[str], link_re: str, url_base: str):
    """Every href matching link_re across every listing page becomes a
    FeedItem (dates come from the item pages at extract time; the runner's
    ledger dedup keeps re-sweeps cheap)."""
    pat = re.compile(link_re)

    async def discover(client) -> list[base.FeedItem]:
        urls: list[str] = []
        for listing in listings:
            try:
                html = (await base.fetch(client, listing)).text
            except Exception:  # noqa: BLE001 — one dead listing page ≠ dead source
                continue
            for m in pat.finditer(html):
                u = m.group(1) if m.groups() else m.group(0)
                u = u if u.startswith("http") else url_base + u
                if u not in urls:
                    urls.append(u)
        return [base.FeedItem(url=u) for u in urls]
    return discover


def make_extract(category: str, selector: str | None = None, min_chars: int = 200):
    """genericrss extraction with a per-source body selector tried first
    (Drupal/SilverStripe decision pages have stable wrappers genericrss's
    news-theme selectors don't cover) and the category stamped on."""
    def extract(html: str, url: str) -> base.Extracted | None:
        ex = None
        if selector:
            soup = BeautifulSoup(html, "html.parser")
            body_el = soup.select_one(selector)
            if body_el is not None:
                paras = [" ".join(p.get_text().split())
                         for p in body_el.find_all(["p", "li", "h2", "h3"])]
                text = "\n\n".join(p for p in paras if p)
                if len(text) < min_chars:
                    # decision pages are often TABLES (OIO: applicant / vendor /
                    # consideration rows) — serialize the whole container
                    text = re.sub(r"\n{3,}", "\n\n",
                                  body_el.get_text("\n", strip=True))
                og = soup.select_one('meta[property="og:title"]')
                h1 = soup.select_one("h1")
                title = ((og.get("content").strip() if og and og.get("content") else "")
                         or (" ".join(h1.get_text().split()) if h1 else ""))
                if not title and soup.title:  # privacy.org.nz: no og:title, no h1
                    title = re.split(r"\s*[|·—]\s*",
                                     " ".join(soup.title.get_text().split()))[0]
                if title and len(text) >= min_chars:
                    ex = base.Extracted(title=title, text=text, author=None,
                                        published_at=None, categories=[])
        if ex is None:
            ex = genericrss.extract(html, url)
        if ex is None:
            return None
        if category not in ex.categories:
            ex.categories.append(category)
        return ex
    return extract
