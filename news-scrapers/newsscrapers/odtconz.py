"""odt.co.nz (Otago Daily Times) — port of the Java ODT scraper
(ops/scraper-service-standalone .../scraper/odtconz/).

Discovery: sitemap-based (discover()), following the Java pipeline
(OdtSitemapParser over https://www.odt.co.nz/sitemap.xml). The Java code
assumed "the first N sitemap pages are the recent ones" — live in 2026 that is
FALSE: the ~12 child pages hold ~50k URLs each and are NOT date-ordered (page
1 is all 2008-2010; the current articles are scattered inside one middle page).
So discover() scans every child page and filters by <lastmod>, returning
newest-first; base.run_source then applies its own recency window + limit.
Cost: ~60-70 MB per full run (each child page is ~6 MB) — acceptable at ODT's
30-min cadence and polite (POLITE_SLEEP between pages), but heavier than a feed.

ODT does expose https://www.odt.co.nz/rss.xml (FEEDS below, for reference) but
it is unusable as a fresh-news source: it serves a small fixed/rotating set of
featured + sponsored items dated 2016-2022, not the live front page. discover()
is therefore the real path; base.run_source prefers it over FEEDS.

Content parsing follows OdtContentScraper selectors:
  title    h1.page-header, fallback meta[property=og:title]
  date     div.dateline — "EEEE, d MMMM yyyy" (start of day UTC, as in Java)
  content  div.field-items div.field-item.even[property=content:encoded],
           skipping text inside <li> (Java filtered li-nested elements);
           fallback: article p
  author   article .field-name-field-source...term-reference a
  cats     breadcrumb <li>s (".breadcrumb li" — live pages have no
           .breadcrumb-wrapper ancestor any more), fallback: URL path
           segments before the hyphenated slug
Deviation: content is paragraph-joined via base.clean_text ("\n\n") instead
of Jsoup's single space-joined text() blob (house style for the ports).

The Java service needed a proxy for ODT (server IP was blocked); direct
connection works from this runtime — if 403/429s appear, wire
ingestion/proxies.py in at the runner level.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import httpx
from bs4 import BeautifulSoup

from . import base

SOURCE = "odt.co.nz"
FEEDS = ["https://www.odt.co.nz/rss.xml"]  # unusable — see docstring; discover() is used

# moved 2026-07-25 (old /sitemap.xml now 404s; robots.txt names the new pair —
# the rurallife index is a separate masthead and is not walked here)
SITEMAP_INDEX = "https://www.odt.co.nz/sitemaps/odt/sitemap_index.xml"
_SM = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
_ROOTS = {"https://www.odt.co.nz/", "https://www.odt.co.nz"}
# only surface urls modified within this window as discovery candidates
# (base.run_source narrows further via its own `since`); bounds candidate volume
_RECENT_DAYS = 21

_CONTENT_SEL = 'div.field-items div.field-item.even[property="content:encoded"]'
_AUTHOR_SEL = ("article .field.field-name-field-source."
               "field-type-taxonomy-term-reference.field-label-hidden a")

# ---- AUTH (measured 2026-11-11) ------------------------------------------
# ODT serves the FULL body to any plain HTTP fetch carrying the logged-in
# Piano cookies (measured: same article = 48-char teaser anon vs 3,881 chars
# of wire copy with the jar). The jar is minted by a one-time browser login
# through the Piano identity iframe at /login (id-au.piano.io form:
# input[name=email] -> input[type=password] -> button[type=submit]; a v2
# reCAPTCHA anchor is present but does not challenge) and persisted to
# odt_state.json (the __utp JWT lasts ~1 year). So fetch_all is plain httpx
# with the persisted jar — no browser per sweep. When the teaser reappears
# (jar expiry), one browser re-login re-mints it (house rule: one attempt,
# then visible thin, never a login hammer).
_STATE_PATH = os.environ.get(
    "ODT_STATE_PATH", "/opt/data/evs-credentials/odt_state.json")
_PAYWALL_MARK = "This story is for subscribers"


def _credentials() -> tuple[str, str]:
    em = os.environ.get("ODT_EMAIL")
    pw = os.environ.get("ODT_PASSWORD")
    if not em or not pw:
        raise RuntimeError(
            "odt credentials not configured: set ODT_EMAIL and ODT_PASSWORD")
    return em, pw


def _cookie_jar() -> dict[str, str]:
    try:
        with open(_STATE_PATH) as fh:
            state = json.load(fh)
    except (FileNotFoundError, ValueError):
        return {}
    return {c["name"]: c["value"] for c in state.get("cookies", [])
            if "odt.co.nz" in c.get("domain", "") or "piano.io" in c.get("domain", "")}


async def _browser_login() -> dict[str, str]:
    """Piano identity iframe login; persists storage state; returns the jar."""
    from playwright.async_api import async_playwright  # lazy — optional dep
    em, pw = _credentials()
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context()
        page = await ctx.new_page()
        await page.goto("https://www.odt.co.nz/login",
                        wait_until="domcontentloaded", timeout=60_000)
        frame = None
        for _ in range(30):
            frame = next((f for f in page.frames if "piano.io/id" in f.url), None)
            if frame is not None:
                break
            await page.wait_for_timeout(500)
        if frame is None:
            raise RuntimeError("odt login: piano identity frame never appeared")
        await frame.wait_for_selector("input[name=email]", timeout=15_000)
        await frame.fill("input[name=email]", em)
        await frame.fill("input[type=password]", pw)
        await frame.click("button[type=submit]")
        await page.wait_for_timeout(8_000)
        jar = {c["name"]: c["value"] for c in await ctx.cookies()
               if "odt.co.nz" in c.get("domain", "") or "piano.io" in c.get("domain", "")}
        if not any(len(v) > 50 and "." in v for k, v in jar.items() if k == "__utp"):
            raise RuntimeError("odt login: no __utp token after submit "
                               "— login did not take")
        await ctx.storage_state(path=_STATE_PATH)
        await browser.close()
    return jar


async def fetch_all(urls: list[str]) -> list[tuple[str, str]]:
    """run_source's auth hook: plain httpx with the persisted Piano cookie
    jar; one browser re-login per run IF the paywall teaser reappears."""
    jar = _cookie_jar()
    if not jar:
        jar = await _browser_login()
    out: list[tuple[str, str]] = []
    async with httpx.AsyncClient(timeout=60, follow_redirects=True,
                                 cookies=jar) as client:
        for url in urls:
            try:
                out.append((url, (await base.fetch(client, url)).text))
            except Exception as e:  # noqa: BLE001
                print(f"  fetch error {url}: {type(e).__name__}: {e}")
                out.append((url, ""))
            await asyncio.sleep(base.POLITE_SLEEP)
    if any(_PAYWALL_MARK in h for _, h in out):
        print("  paywall teaser in batch — re-login once and refetch")
        jar = await _browser_login()
        async with httpx.AsyncClient(timeout=60, follow_redirects=True,
                                     cookies=jar) as client:
            for i, (url, html) in enumerate(out):
                if _PAYWALL_MARK in html:
                    try:
                        out[i] = (url, (await base.fetch(client, url)).text)
                    except Exception:  # noqa: BLE001
                        pass
                    await asyncio.sleep(base.POLITE_SLEEP)
    return out


def _text(el) -> str:
    """Jsoup Element.text() equivalent: whitespace-collapsed, trimmed."""
    return " ".join(el.get_text().split()) if el is not None else ""


def _parse_date(dateline: str) -> datetime | None:
    """"Thursday, 3 February 2022" → start of day UTC (OdtContentScraper)."""
    s = " ".join((dateline or "").split())
    try:
        return datetime.strptime(s, "%A, %d %B %Y").replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _categories_from_url(url: str) -> list[str]:
    """Path segments before the hyphenated slug
    (OdtSitemapParser.ArticleLink.extractCategoriesFromUrl)."""
    path = re.sub(r"^https?://[^/]+/", "", url or "")
    parts = [p for p in path.split("/") if p]
    cats: list[str] = []
    for part in parts:
        if "-" in part and parts and parts[-1] == part:
            break
        cats.append(part)
    return cats


def _sitemap_lastmod(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def discover(client) -> list[base.FeedItem]:
    """Scan every child sitemap page, keep recent-lastmod article urls,
    newest first (see module docstring for why paging can't be short-cut)."""
    try:
        index = (await base.fetch(client, SITEMAP_INDEX)).text
    except Exception as e:  # noqa: BLE001
        print(f"  sitemap index error: {type(e).__name__}: {e}")
        return []
    pages = [loc.text.strip() for loc in ET.fromstring(index.encode()).iter(_SM + "loc")
             if loc.text and loc.text.strip()]

    cutoff = datetime.now(timezone.utc) - timedelta(days=_RECENT_DAYS)
    items: list[base.FeedItem] = []
    for page in pages:
        await asyncio.sleep(base.POLITE_SLEEP)
        try:
            root = ET.fromstring((await base.fetch(client, page)).text.encode())
        except Exception as e:  # noqa: BLE001
            print(f"  sitemap page error {page}: {type(e).__name__}: {e}")
            continue
        for u in root.iter(_SM + "url"):
            loc = (u.findtext(_SM + "loc") or "").strip()
            if not loc or loc in _ROOTS:
                continue
            lastmod = _sitemap_lastmod(u.findtext(_SM + "lastmod"))
            if lastmod is None or lastmod < cutoff:
                continue
            items.append(base.FeedItem(
                url=loc, published_at=lastmod,
                category=(_categories_from_url(loc) or [None])[0]))
    items.sort(key=lambda i: i.published_at or datetime.min.replace(
        tzinfo=timezone.utc), reverse=True)
    return items


def extract(html: str, url: str) -> base.Extracted | None:
    soup = BeautifulSoup(html, "html.parser")

    title = _text(soup.select_one("h1.page-header"))
    if not title:
        og = soup.select_one('meta[property="og:title"]')
        title = (og.get("content") or "").strip() if og else ""

    published_at = None
    # 2026-11-11 redesign (Next.js): div.dateline is gone; JSON-LD is the
    # live hook (datePublished e.g. "2026-11-11T16:30:00Z").
    m = re.search(r'"datePublished"\s*:\s*"([^"]+)"', html)
    if m:
        try:
            published_at = datetime.fromisoformat(
                m.group(1).strip().replace("Z", "+00:00"))
        except ValueError:
            published_at = None
    if published_at is None:
        dateline = _text(soup.select_one("div.dateline"))
        if dateline:
            published_at = _parse_date(dateline)

    # content: the content:encoded container, minus anything nested in <li>
    parts: list[str] = []
    container = soup.select_one(_CONTENT_SEL)
    if container is not None:
        for el in container.find_all(["p", "h2", "h3"]):
            if el.find_parent("li") is None:
                parts.append(_text(el))
        if not any(parts):  # bare-text container without <p> wrappers
            parts = [_text(container)]
    if not any(parts):  # Java fallback: article p
        parts = [_text(p) for p in soup.select("article p")]
    text = base.clean_text(parts)
    if not text:
        return None

    author = None
    author_el = soup.select_one(_AUTHOR_SEL)
    if author_el is None:
        # 2026-11-11 redesign: byline lives in a .byline-card block
        author_el = soup.select_one(".byline-card")
    if author_el is not None:
        author = _text(author_el) or None
        if author:
            author = author.split("\n")[0][:80] or None

    categories = [_text(li) for li in soup.select(".breadcrumb li")]
    categories = [c for c in categories if c]
    if not categories:
        categories = _categories_from_url(url)

    return base.Extracted(title=title, text=text, author=author,
                          published_at=published_at, categories=categories)
