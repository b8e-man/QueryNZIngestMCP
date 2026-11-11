"""businessdesk.co.nz — port of the Java Businessdesk scraper
(ops/scraper-service-standalone .../scraper/businessdesk/). Paywalled; the
Java scraper was DISABLED at the client's request because automated login
stopped working (suspected added CAPTCHA / device fingerprinting).

Discovery: sitemap-based (SitemapParser). discover() fetches
https://businessdesk.co.nz/index-sitemap.xml, keeps the monthly
"articles-sitemap-YYYYMM" child sitemaps for the last _MONTHS_TO_SCAN months
(the Java incremental mode fetched only months covering [newest-in-DB ..
today]; run_source's hours-window replaces the DB high-watermark), and reads
loc + lastmod per entry (both required, as in Java).

Content parsing follows BusinessdeskScraper.collectInnerInfo(): article
container "div.row.individual-story" with "section div.row" fallback; title
".article-title" (fallback: the URL string, as Java did); content
".article-body"; date ".story-date" via RFC-1123 — with " 00:00:00 GMT"
appended when the text has no time — else ISO offset; categories the
".d-flex.justify-content-between" breadcrumb split on "/" and de-duplicated;
author ".author-name a" (profile href not kept — Extracted has no field).
Deviation: content is paragraph-joined via base.clean_text instead of raw
textContent (no goldens pin the shape). Java's per-field try/catch +
partial-save becomes: container or body missing -> None; everything else
best-effort.

AUTH (BLOCKED — and known-broken even in Java): login flow ported from
performSignIn()/signInPage(): open the site, check #navbarNav for
"My Account", else the /login page — input[name=email], input[name=password],
#set-remember checkbox, button[type=submit] (Java typed human-like to dodge
bot detection). Credentials from BUSINESSDESK_EMAIL / BUSINESSDESK_PASSWORD
(names as in docker/.env.example); a clear error is raised when unset.
"""
from __future__ import annotations

import asyncio
import email.utils
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from bs4 import BeautifulSoup

from . import base

SOURCE = "businessdesk.co.nz"
FEEDS: list[str] = []  # sitemap discovery — see discover()

BASE_URL = "https://businessdesk.co.nz"
SITEMAP_INDEX = ("https://www.businessdesk.co.nz/arc/outboundfeeds/"
                 "sitemap-index/?outputType=xml")
# ruling 169 (Arthur, 2026-11-11): collect from 2026-10-17, when the old
# estate's scrapers stopped. The Arc index carries dated sub-sitemaps, so
# the cutoff is a date filter on the children we walk.
CUTOFF = "2026-10-17"
# a BusinessDesk article URL is <section>/<slug>/<26-char Arc id>/ — the
# same Arc-id tail family as the nzme module; /premium/ is paywalled and
# dropped at discovery (never fetched, never bypassed).
_ARC_TAIL = r"/[A-Z0-9]{24,}/?$"
_ARTICLE = re.compile(r"^https?://www\.businessdesk\.co\.nz/\S+" + _ARC_TAIL)
_LOC = re.compile(r"<loc>\s*(.*?)\s*</loc>", re.S)
_MONTHS_TO_SCAN = 2
_SM = "{http://www.sitemaps.org/schemas/sitemap/0.9}"

_LOGIN_URL = (BASE_URL + "/login?redirect_uri=https%3A%2F%2Fbusinessdesk.co.nz"
              "%2Farticle%2Ftechnology%2Frocket-lab-at-20-from-pipe-dream-to-"
              "50-billion-space-empire")


def _text(el) -> str:
    """Jsoup Element.text() equivalent: whitespace-collapsed, trimmed."""
    return " ".join(el.get_text().split()) if el is not None else ""


# --------------------------------------------------------------------------
# Discovery (SitemapParser)
# --------------------------------------------------------------------------

def _recent_month_tokens(n: int) -> list[str]:
    """['articles-sitemap-YYYYMM', ...] for the current and previous months."""
    now = datetime.now(timezone.utc)
    year, month = now.year, now.month
    out = []
    for _ in range(n):
        out.append(f"articles-sitemap-{year:04d}{month:02d}")
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return out


def _lastmod(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def discover(client) -> list[base.FeedItem]:
    """Arc sitemap-index -> dated sub-sitemaps (>= CUTOFF) + latest -> urls.

    The old monthly `articles-sitemap-YYYYMM` shape is gone (measured
    2026-11-11: index-sitemap.xml 404s; robots.txt now lists the Arc
    outboundfeeds, same family as the nzme module). Newest-first."""
    try:
        index_xml = (await base.fetch(client, SITEMAP_INDEX)).text
    except Exception as e:  # noqa: BLE001
        print(f"  businessdesk index error: {type(e).__name__}: {e}")
        return []
    children = [u.replace("&amp;", "&").strip()
                for u in _LOC.findall(index_xml)]
    wanted = []
    for u in children:
        m = re.search(r"/sitemap\d?/(\d{4}-\d{2}-\d{2})/", u)
        if m:
            if m.group(1) >= CUTOFF:
                wanted.append(u)
        elif "/sitemap/latest/" in u:
            wanted.append(u)

    seen: set[str] = set()
    items: list[base.FeedItem] = []
    for sm_url in wanted:
        await asyncio.sleep(base.POLITE_SLEEP)
        try:
            xml = (await base.fetch(client, sm_url)).text
        except Exception as e:  # noqa: BLE001
            print(f"  sitemap error {sm_url}: {type(e).__name__}: {e}")
            continue
        for raw in _LOC.findall(xml):
            loc = raw.replace("&amp;", "&").strip()
            if loc in seen or "/premium/" in loc:
                continue
            if _ARTICLE.match(loc):
                seen.add(loc)
                items.append(base.FeedItem(url=loc))
    return items


# --------------------------------------------------------------------------
# Extraction (BusinessdeskScraper.collectInnerInfo)
# --------------------------------------------------------------------------

def parse_article_date(date_str: str | None) -> datetime | None:
    """Port of BusinessdeskScraper.parseArticleDate: RFC-1123 (appending
    " 00:00:00 GMT" when the text carries no time) with ISO-offset fallback.
    Arc redesign (2026-11-11): bare "8 Nov, 2026 11:41pm" style added."""
    s = (date_str or "").strip()
    if not s:
        return None
    if ":" not in s:
        s += " 00:00:00 GMT"
    try:
        return email.utils.parsedate_to_datetime(s)
    except (TypeError, ValueError):
        for fmt in ("%d %b, %Y %I:%M%p", "%d %b, %Y %I:%M %p"):
            try:
                return datetime.strptime(
                    s.replace("am", "am").replace("pm", "pm"), fmt
                ).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None


_ARC_SKIP_P = re.compile(
    r"^(reminder, this is a premium article|give paywall-free access|"
    r"advertisement|sign up|subscribe to)", re.I)


def _arc_extract(soup, url: str) -> base.Extracted | None:
    """Arc/Fusion article shape (measured live 2026-11-11): h1 title,
    header.article__header carries title/author/role/date lines, bare <p>
    body outside the chrome (no classed body container — tailwind only)."""
    h1 = soup.find("h1")
    title = _text(h1) or ((soup.select_one("meta[property='og:title']") or {})
                          .get("content") or "").strip() or url

    published_at = None
    t = soup.find("time")
    if t is not None:
        published_at = parse_article_date(_text(t))

    author = None
    header = soup.select_one("header.article__header")
    if header is not None:
        lines = [l.strip() for l in header.get_text("\n").splitlines()
                 if l.strip()]
        for l in lines[1:]:
            if re.match(r"^\d{1,2} \w{3}, \d{4}", l):
                break
            if l.lower() in ("follow author", "listen", "gift article",
                             "save", "share", "quick read"):
                break
            author = l
            break

    parts = []
    for p in soup.find_all("p"):
        if p.find_parent(["nav", "footer", "aside", "header"]):
            continue
        txt = _text(p)
        if len(txt) < 40 or _ARC_SKIP_P.match(txt):
            continue
        parts.append(txt)
    text = base.clean_text(parts)
    return base.Extracted(title=title, text=text or None, author=author,
                          published_at=published_at, categories=[])


def extract(html: str, url: str) -> base.Extracted | None:
    soup = BeautifulSoup(html, "html.parser")
    for br in soup.find_all("br"):
        br.replace_with("\n")

    article = (soup.select_one("div.row.individual-story")
               or soup.select_one("section div.row"))
    if article is None:
        # Arc redesign (2026-11-11) — the Bootstrap containers are gone
        return _arc_extract(soup, url)

    body = soup.select_one(".article-body")
    if body is None:
        return None  # Java: "Article body not found" (paywall wall page)
    parts = [_text(p) for p in body.find_all(["p", "h2", "h3", "li"])]
    text = base.clean_text(parts) or _text(body)
    if not text:
        return None

    title = _text(soup.select_one(".article-title")) or url  # Java fallback: URL

    published_at = parse_article_date(_text(soup.select_one(".story-date")))

    categories: list[str] = []
    crumb = soup.select_one(".d-flex.justify-content-between")
    if crumb is not None:
        seen: set[str] = set()
        for c in _text(crumb).split("/"):
            c = c.strip()
            if c and c not in seen:
                seen.add(c)
                categories.append(c)

    author_el = soup.select_one(".author-name a")
    author = (_text(author_el) or None) if author_el is not None else None

    return base.Extracted(title=title, text=text, author=author,
                          published_at=published_at, categories=categories)


# --------------------------------------------------------------------------
# Authenticated fetch (BLOCKED — login was broken even in the Java service)
# --------------------------------------------------------------------------

def _credentials() -> tuple[str, str]:
    em = os.environ.get("BUSINESSDESK_EMAIL")
    pw = os.environ.get("BUSINESSDESK_PASSWORD")
    if not em or not pw:
        raise RuntimeError(
            "businessdesk credentials not configured: set BUSINESSDESK_EMAIL "
            "and BUSINESSDESK_PASSWORD (names as in ops/scraper-service-"
            "standalone/docker/.env.example)")
    return em, pw


async def _perform_sign_in(page) -> None:
    """Arc identity flow (measured live 2026-11-11): /login/ -> "Sign In"
    button -> /my-account/identity/ (emailAddress -> continue ->
    password-field -> submit). The old #navbarNav/input[name=email] flow is
    gone with the Arc redesign. Java typed human-like (per-char delay) to
    dodge bot detection — kept."""
    em, pw = _credentials()
    await page.goto("https://www.businessdesk.co.nz/login/",
                    wait_until="domcontentloaded", timeout=60_000)
    try:
        await page.get_by_text("Sign In", exact=True).first.click(timeout=10_000)
    except Exception:
        pass                                  # already on the identity page
    await page.wait_for_selector("input[name='emailAddress']", timeout=15_000)
    await page.type("input[name='emailAddress']", em, delay=120)
    try:
        await page.get_by_role("button").filter(
            has_text=re.compile(r"continue|sign in|next", re.I)
        ).first.click(timeout=8_000)
    except Exception:
        await page.keyboard.press("Enter")
    await page.wait_for_selector("input[name='password']", timeout=15_000)
    await page.type("input[name='password']", pw, delay=120)
    try:
        await page.get_by_role("button").filter(
            has_text=re.compile(r"sign in|log ?in|submit", re.I)
        ).first.click(timeout=8_000)
    except Exception:
        await page.keyboard.press("Enter")
    await page.wait_for_timeout(6_000)


async def _sign_in_if_needed(page) -> None:
    """Signed in = the account menu renders (measured 2026-11-11:
    a[href*='/my-account/profile'] appears only when authenticated — the
    /my-account/subscription/offers/ 'Subscribe' link is marketing and
    present logged-out too)."""
    await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=60_000)
    try:
        await page.wait_for_selector(
            'a[href*="/my-account/profile"]', timeout=10_000)
        return                                # already signed in
    except Exception:
        pass
    await _perform_sign_in(page)


async def fetch_all(urls: list[str]) -> list[tuple[str, str]]:
    """run_source's auth hook — one signed-in browser context for the batch."""
    return await fetch_authenticated(urls)


async def fetch_authenticated(urls: list[str], *,
                              headless: bool | None = None) -> list[tuple[str, str]]:
    """Sign in (if needed) then fetch article pages, returning (url, html).
    NOTE: automated login is the reason the Java scraper was shelved — expect
    this to need a manually captured session or CAPTCHA solving.
    """
    _credentials()  # fail fast with a clear error before launching a browser
    if headless is None:
        headless = os.environ.get("BUSINESSDESK_HEADLESS", "true").lower() != "false"

    from playwright.async_api import async_playwright  # lazy — optional dep

    out: list[tuple[str, str]] = []
    import proxies   # the ONE proxy helper (C207): opt-in, None unless a heavy run asks
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless,
                                           proxy=proxies.playwright_proxy("businessdesk"))
        page = await browser.new_page()
        await _sign_in_if_needed(page)
        for url in urls:
            await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            out.append((url, await page.content()))
            await asyncio.sleep(base.POLITE_SLEEP)
        await browser.close()
    return out
