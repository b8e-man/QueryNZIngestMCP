"""beehive.govt.nz — port of the Java Beehive scraper
(ops/scraper-service-standalone .../scraper/beehivegovtnz/).

Discovery: like BeehivegovtnzRssScraper, feed URLs are discovered dynamically
from https://www.beehive.govt.nz/feeds ("ul.all-site-feeds li a", the
/features/feed excluded), falling back to the hardcoded FEEDS list if the
discovery page fails. The Java sitemap track (historical coverage with
https://default/ URL rewriting) is NOT ported — RSS covers fresh news.

Content parsing follows BeehivegovtnzContentScraper's selectors. Deviation
from Java: plain HTTP fetch instead of Playwright/headless-Firefox (the Java
comments note the site is publicly accessible; the browser was mainly for
cookie consistency). If live runs turn out to be bot-blocked, this source
needs the browser path back.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from . import base

SOURCE = "beehive.govt.nz"
BASE_URL = "https://www.beehive.govt.nz/"
RELEASES_URL = "https://www.beehive.govt.nz/releases"
FEEDS_PAGE = "https://www.beehive.govt.nz/feeds"
FEEDS = ["https://www.beehive.govt.nz/feed"]  # fallback when discovery fails

_NZ = ZoneInfo("Pacific/Auckland")
_CONTENT_SEL = ".region-content .prose.field--name-body > *:not(script):not(style)"
_CONTENT_SEL_ALT = ".region-content .field.field--name-body > *:not(script):not(style)"
_CATEGORY_SEL = "ol.breadcrumb li a"
_CATEGORY_SEL_ALT = ("div.tag.taxonomy-term--type-portfolios a, "
                     "em.tag--portfolio span.is-archived")


def _text(el) -> str:
    """Jsoup Element.text() equivalent: whitespace-collapsed, trimmed."""
    return " ".join(el.get_text().split()) if el is not None else ""


async def discover(client) -> list[base.FeedItem]:
    """Discovery via the rendered /releases index — beehive is behind Incapsula
    (2026-07-16), so plain httpx gets the JS-challenge shell and the RSS 404s.
    A headless browser renders the release list; dates come from each article
    page at fetch time. Falls back to the RSS feeds if the browser path is
    unavailable (they only work if Incapsula ever eases)."""
    from . import browserfetch
    try:
        pairs = await browserfetch.render_all([RELEASES_URL], settle_ms=1000)
    except Exception as e:  # noqa: BLE001 — no browser → RSS fallback
        print(f"  beehive browser discovery unavailable ({type(e).__name__}) — RSS fallback")
        return await _discover_rss(client)
    if not pairs:
        return await _discover_rss(client)

    soup = BeautifulSoup(pairs[0][1], "html.parser")
    seen: set[str] = set()
    items: list[base.FeedItem] = []
    for a in soup.select("a[href*='/release/']"):
        href = urljoin(BASE_URL, (a.get("href") or "").strip())
        if "/release/" not in href or href in seen:
            continue
        seen.add(href)
        items.append(base.FeedItem(url=href, title=_text(a) or None))
    return items


async def _discover_rss(client) -> list[base.FeedItem]:
    """Original RSS discovery — kept as the fallback."""
    feeds: list[str] = []
    try:
        html = (await base.fetch(client, FEEDS_PAGE)).text
        for a in BeautifulSoup(html, "html.parser").select("ul.all-site-feeds li a"):
            href = (a.get("href") or "").strip()
            if href and "/features/feed" not in href:
                feeds.append(urljoin(BASE_URL, href))
    except Exception as e:  # noqa: BLE001
        print(f"  feed discovery error {FEEDS_PAGE}: {type(e).__name__}: {e}")
    if not feeds:
        feeds = list(FEEDS)

    items: list[base.FeedItem] = []
    for feed in feeds:
        await asyncio.sleep(base.POLITE_SLEEP)
        try:
            items += base.parse_rss((await base.fetch(client, feed)).text)
        except Exception as e:  # noqa: BLE001
            print(f"  feed error {feed}: {type(e).__name__}: {e}")
    return items


async def fetch_all(urls: list[str]) -> list[tuple[str, str]]:
    """run_source's fetch hook — every article via the headless browser
    (Incapsula blocks plain httpx)."""
    from . import browserfetch
    return await browserfetch.render_all(urls)


def extract(html: str, url: str) -> base.Extracted | None:
    soup = BeautifulSoup(html, "html.parser")
    for br in soup.find_all("br"):
        br.replace_with("\n")

    title = _text(soup.select_one("h1.article__title"))

    published_at = None
    date_el = (soup.select_one("time.meta__date time[datetime]")
               or soup.select_one("time.meta__date[datetime]"))
    if date_el is not None:
        try:
            published_at = datetime.fromisoformat(
                date_el["datetime"].strip().replace("Z", "+00:00")).astimezone(_NZ)
        except ValueError:
            published_at = None

    chosen = soup.select(_CONTENT_SEL) or soup.select(_CONTENT_SEL_ALT)
    if not chosen:
        return None
    text = base.clean_text([_text(el) for el in chosen])
    if not text:
        return None

    author = (_text(soup.select_one(".minister__title"))
              or _text(soup.select_one("span.is-archived"))) or None

    categories: list[str] = []
    seen: set[str] = set()
    for el in soup.select(_CATEGORY_SEL) + soup.select(_CATEGORY_SEL_ALT):
        c = _text(el)
        if c and c.lower() != "home" and c.lower() not in seen:
            seen.add(c.lower())
            categories.append(c)

    return base.Extracted(title=title, text=text, author=author,
                          published_at=published_at, categories=categories)
