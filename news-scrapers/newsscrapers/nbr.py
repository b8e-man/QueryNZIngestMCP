"""nbr.co.nz — port of the Java NBR scraper
(ops/scraper-service-standalone .../scraper/nbr/). Paywalled: a subscriber
account is required for full article bodies.

Discovery: sitemap-based, as in the active Java pipeline (NbrSitemapScraper).
discover() fetches https://www.nbr.co.nz/sitemap.xml and walks EVERY child
sitemap (Java MAX_PAGES parity: _MAX_SITEMAPS = 200), yielding article urls
+ lastmod (title synthesised from the slug, as in Java). Deviations: plain
httpx instead of a Playwright-rendered fetch (the sitemap serves fine to
plain httpx — measured 2026-11-11), only sitemap>loc index entries are
selected (fixes the Java "sitemap > loc, loc" known issue). Measured
2026-11-11: the child scan CANNOT be short-cut — fresh urls land in tree
order by SECTION (today's articles sat in children 108-112 of 112, with
109 empty; child 1's newest was 5 days old), so a "newest children" or
"head children" heuristic misses sections. The index's per-child lastmod
is useless too (all 112 identical = regeneration time). An earlier port
cap of [:5] therefore returned 0 fresh items for 72h. POLITE_SLEEP = 10
honors robots.txt Crawl-Delay: 10 (a full scan is ~20 min — fine inside
the daily tick). The Java RSS path (NbrRssScraper: /rss/ page -> per-category feed
urls from "div.styled-content ul li a") is ported as discover_rss() but,
exactly as in Java, it is NOT the active discovery mechanism (the @Scheduled
was commented out) — and it is INSUFFICIENT as a substitute: the 9 feeds
cover only 9 sections (10 items each) while fresh articles also land in
primary-industries, professional-services, tourism, comings-and-goings,
edwards-on-politics and others (measured 2026-11-11).

Content parsing follows NbrContentScraper + NbrContentResolver: per-page
layout detection — ".page-richlistmain" present -> V2 selectors,
".page-radar-article" -> V3, else V1 — then title/content/author from the
resolved selector set, date from meta[property="article:published_time"]
("d MMMM yyyy" at Pacific/Auckland midnight, else ISO), category = first URL
path segment. Deviation: content is paragraph-joined via base.clean_text
instead of Jsoup's single space-collapsed text() blob (no goldens pin the
shape; \n\n reads better downstream).

AUTH (BLOCKED without credentials): the Java NbrLogInService automates a
Chromium (headless=False under Xvfb) login and extracts three cookies —
SECSESSID, alc_enc, alc_device — cached for 3 days and injected into the
shared browser context; every navigation is then checked for the
account icon ('a.user-collapsible-icon[href*="my-account"]'). login() ports
that flow; it reads NBR_ACCOUNT_EMAIL / NBR_ACCOUNT_PASSWORD (+ optional
NBR_PROXY host:port:user:pass), matching application.properties, and raises
a clear error when unset. Unauthenticated fetches get the teaser only —
run_source's 200-char floor drops most of those.
"""
from __future__ import annotations

import asyncio
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from . import base

SOURCE = "nbr.co.nz"
FEEDS: list[str] = []  # sitemap discovery — see discover(); RSS disabled in Java

WWW_BASE_URL = "https://www.nbr.co.nz/"
SITEMAP_INDEX = "https://www.nbr.co.nz/sitemap.xml"
RSS_INDEX = "https://www.nbr.co.nz/rss/"
_MAX_SITEMAPS = 200  # Java MAX_PAGES parity — the FULL child set (see docstring: fresh urls land in any child)
POLITE_SLEEP = 10.0  # robots.txt declares Crawl-Delay: 10 — honored for every fetch (full scan ~20 min, daily tick absorbs it)
_SM = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
_NZ = ZoneInfo("Pacific/Auckland")

# NbrConstants.LINKS_TO_IGNORE — non-article feed/category index pages
LINKS_TO_IGNORE = {
    "https://nbr.co.nz/podcasts/",
    "https://nbr.co.nz/nz-aviation-news/",
    "https://nbr.co.nz/politics/",
    "https://nbr.co.nz/rss/",
    "https://nbr.co.nz/law/",
    "https://nbr.co.nz/tech/",
    "https://nbr.co.nz/nbr-view/",
}

# (title, content, author_info, author_name) — V{1,2,3}ContentConstants
_V1 = ("h1.size-2", ".article-content.styled-content",
       ".journalist-info", ".journalist-name")
_V2 = (".page-rich-list-article h1", ".page-rich-list-article .rich-list-article-content",
       ".journalist-info", ".journalist-info .journalist-name")
_V3 = (".radar-title h1", ".page-radar-article .radar-content",
       ".radar-journalist", ".radar-journalist .journalist-name")
_DATE_SEL = 'meta[property="article:published_time"]'
_ACCOUNT_ICON_SEL = 'a.user-collapsible-icon[href*="my-account"]'


def _text(el) -> str:
    """Jsoup Element.text() equivalent: whitespace-collapsed, trimmed."""
    return " ".join(el.get_text().split()) if el is not None else ""


# --------------------------------------------------------------------------
# Discovery (NbrSitemapScraper)
# --------------------------------------------------------------------------

def _lastmod(s: str | None) -> datetime | None:
    if not s:
        return None
    s = s.strip()
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        try:  # Java fallback: bare LocalDate at UTC midnight
            dt = datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _slug_title(url: str) -> str | None:
    # Java: capitalize(substringAfterLast(url minus .htm suffix, "/").replace("-", " "))
    path = urlsplit(url).path
    if path.endswith(".htm") or ".htm" in path.rsplit("/", 1)[-1]:
        path = path[:path.rfind(".htm")]
    slug = path.rstrip("/").rsplit("/", 1)[-1]
    if not slug:
        return None
    title = slug.replace("-", " ")
    return title[:1].upper() + title[1:]


async def discover(client) -> list[base.FeedItem]:
    """Sitemap index -> newest child sitemaps -> article urls + lastmod."""
    index_xml = (await base.fetch(client, SITEMAP_INDEX)).text
    root = ET.fromstring(index_xml.encode())
    children = [(loc.text or "").strip()
                for sm in root.iter(_SM + "sitemap")
                for loc in sm.iter(_SM + "loc") if loc.text]
    items: list[base.FeedItem] = []
    for sm_url in children[:_MAX_SITEMAPS]:
        await asyncio.sleep(POLITE_SLEEP)
        try:
            page = ET.fromstring((await base.fetch(client, sm_url)).text.encode())
        except Exception as e:  # noqa: BLE001
            print(f"  sitemap error {sm_url}: {type(e).__name__}: {e}")
            continue
        for u in page.iter(_SM + "url"):
            loc = (u.findtext(_SM + "loc") or "").strip()
            if not loc or loc in LINKS_TO_IGNORE:
                continue
            # the sitemap lists the site root (and section roots) with fresh
            # lastmod — never articles; a shallow path can't be a story
            if len(loc.rstrip("/").split("/")) < 5:
                continue
            items.append(base.FeedItem(
                url=loc, title=_slug_title(loc),
                published_at=_lastmod(u.findtext(_SM + "lastmod"))))
    items.sort(key=lambda i: i.published_at or datetime.min.replace(
        tzinfo=timezone.utc), reverse=True)
    return items


async def discover_rss(client) -> list[base.FeedItem]:
    """Port of NbrRssScraper (DISABLED in Java — kept for parity/fallback):
    the /rss/ page lists per-category feeds in div.styled-content ul li a."""
    html = (await base.fetch(client, RSS_INDEX)).text
    soup = BeautifulSoup(html, "html.parser")
    feed_urls = [a.get("href", "").strip()
                 for a in soup.select("div.styled-content ul li a")]
    items: list[base.FeedItem] = []
    for feed_url in feed_urls:
        if not feed_url or feed_url in LINKS_TO_IGNORE:
            continue
        await asyncio.sleep(POLITE_SLEEP)
        try:
            items += base.parse_rss((await base.fetch(client, feed_url)).text)
        except Exception as e:  # noqa: BLE001
            print(f"  rss error {feed_url}: {type(e).__name__}: {e}")
    return items


# --------------------------------------------------------------------------
# Extraction (NbrContentScraper + NbrContentResolver)
# --------------------------------------------------------------------------

def _resolve(soup: BeautifulSoup) -> tuple[str, str, str, str]:
    if soup.select_one(".page-richlistmain") is not None:
        return _V2
    if soup.select_one(".page-radar-article") is not None:
        return _V3
    return _V1


def _parse_date(s: str) -> datetime | None:
    s = (s or "").strip()
    if not s:
        return None
    try:  # Java: "d MMMM yyyy" at Pacific/Auckland start of day
        return datetime.strptime(s, "%d %B %Y").replace(tzinfo=_NZ)
    except ValueError:
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None


def has_account_logged_icon(html: str) -> bool:
    """Port of NbrLogInService.hasAccountLoggedIcon — the per-page login check."""
    return BeautifulSoup(html, "html.parser").select_one(_ACCOUNT_ICON_SEL) is not None


def extract(html: str, url: str) -> base.Extracted | None:
    soup = BeautifulSoup(html, "html.parser")
    for br in soup.find_all("br"):
        br.replace_with("\n")

    title_sel, content_sel, ainfo_sel, aname_sel = _resolve(soup)

    title = _text(soup.select_one(title_sel))
    content_el = soup.select_one(content_sel)
    if content_el is None or not title:
        return None  # Java: ContentError("No content element found")

    parts = [_text(p) for p in content_el.find_all(["p", "h2", "h3", "li"])]
    text = base.clean_text(parts) or _text(content_el)
    if not text:
        return None  # Java: ContentError("No content extracted")

    published_at = None
    meta = soup.select_one(_DATE_SEL)
    if meta is not None:
        published_at = _parse_date(meta.get("content", ""))

    author = None
    author_block = soup.select_one(ainfo_sel)
    if author_block is not None:  # profile href not kept — Extracted has no field
        author = _text(author_block.select_one(aname_sel)) or None

    # Java: url path segment after the base url
    segs = urlsplit(url).path.strip("/").split("/")
    categories = [segs[0]] if segs and segs[0] else []

    return base.Extracted(title=title, text=text, author=author,
                          published_at=published_at, categories=categories)


# --------------------------------------------------------------------------
# Authenticated fetch (BLOCKED — needs subscriber credentials; NOT live-tested)
# --------------------------------------------------------------------------

_LOG_IN_BUTTON = 'a.user-collapsible-icon-login[href*="Security/login"]'
_EMAIL_INPUT = "#NBRLoginForm_LoginForm_Email"
_PASSWORD_INPUT = "#NBRLoginForm_LoginForm_Password"
_SUBMIT_BUTTON = "#NBRLoginForm_LoginForm_action_doLogin"
_COOKIE_NAMES = ("SECSESSID", "alc_enc", "alc_device")
_COOKIE_DOMAIN = ".nbr.co.nz"


def _credentials() -> tuple[str, str]:
    email = os.environ.get("NBR_ACCOUNT_EMAIL")
    password = os.environ.get("NBR_ACCOUNT_PASSWORD")
    if not email or not password:
        raise RuntimeError(
            "nbr credentials not configured: set NBR_ACCOUNT_EMAIL and "
            "NBR_ACCOUNT_PASSWORD (names as in the Java service's "
            "application.properties)")
    return email, password


def _proxy_config() -> dict | None:
    """NBR_PROXY in Java format host:port:user:pass -> playwright proxy dict.

    Deliberately NOT `proxies.playwright_proxy` (C207, queue 10 2026-09-18):
    NBR_PROXY is the subscription's own login proxy from the Java port — a
    credentialed session route, not the metered NZ-residential pool the helper
    hands out for heavy scrapes. Empty = direct, as before."""
    raw = os.environ.get("NBR_PROXY", "").strip()
    if not raw:
        return None
    host, port, user, pw = (raw.split(":") + [None] * 4)[:4]
    proxy: dict = {"server": f"http://{host}:{port}"}
    if user:
        proxy.update(username=user, password=pw or "")
    return proxy


async def login(*, headless: bool = False) -> dict[str, str]:
    """Port of NbrLogInService.logIn(): automated Chromium login, returns the
    three session cookies. Java ran headless=False under Xvfb (NBR appears to
    detect headless browsers); cache the result — Java kept it for 3 days.
    """
    email, password = _credentials()
    from playwright.async_api import async_playwright  # lazy — optional dep

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless, proxy=_proxy_config())
        page = await browser.new_page()
        # 2026-07-16: navigate straight to the login page instead of clicking
        # the header button — the Java-era selector still exists in the DOM but
        # only in the COLLAPSED mobile menu (hidden), so click() times out
        # waiting for visibility. The href is stable: Security/login?BackURL=/.
        await page.goto(WWW_BASE_URL + "Security/login?BackURL=/",
                        wait_until="domcontentloaded", timeout=120_000)
        await page.fill(_EMAIL_INPUT, email)
        await page.fill(_PASSWORD_INPUT, password)
        await page.click(_SUBMIT_BUTTON)
        await page.wait_for_selector(_ACCOUNT_ICON_SEL, state="visible",
                                     timeout=40_000)
        cookies = {c["name"]: c["value"] for c in await page.context.cookies()}
        await browser.close()
    return {name: cookies.get(name, "") for name in _COOKIE_NAMES}


_COOKIE_TTL_S = 3 * 86400   # Java cached the session for 3 days
# NBR serves headless Chromium an interstitial (the Java-era detection), but
# the login form is plain server-rendered SilverStripe over HTTP: GET the login
# page for the CSRF SecurityID, POST the form, keep the session cookies. No
# browser needed at all (2026-07-16).
_LOGIN_PAGE = WWW_BASE_URL + "Security/login?BackURL=/"
_LOGIN_POST = WWW_BASE_URL + "Security/login/default/LoginForm/"
_SESSIONS_PAGE = WWW_BASE_URL + "my-account/sessions/"  # session-limit bounce target
# Session-limit bounce (measured 2026-11-11): the account allows 3 active
# sessions; with 4 up, EVERY article 302-redirects to /my-account/sessions/
# ("Session Limit Exceeded ... choose a session to end") and
# follow_redirects serves that shell as a 200 article — 43/43 thin, silent.
# Heal: disconnect sessions >72h inactive ("last active N days ago" in the
# block text; 'Current' is always kept), then retry once. Stale threshold
# matches _COOKIE_TTL_S — a session untouched longer than our own cache TTL
# cannot be a live reader.
_BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


async def _login_http(client) -> None:
    """Plain-HTTP login on the given httpx client (cookies land in its jar)."""
    email, password = _credentials()
    page = (await client.get(_LOGIN_PAGE)).text
    sec = BeautifulSoup(page, "html.parser").select_one(
        "input[name='SecurityID']")
    if sec is None or not sec.get("value"):
        raise RuntimeError("nbr login page had no SecurityID (layout change?)")
    r = await client.post(_LOGIN_POST, data={
        "AuthenticationMethod": "DrupalHashCompatibleAuthenticator",
        "BackURL": "/", "Remember": "value",
        "Email": email, "Password": password,
        "SecurityID": sec["value"], "action_doLogin": "Log in",
    })
    r.raise_for_status()
    home = (await client.get(WWW_BASE_URL)).text
    if not has_account_logged_icon(home):
        raise RuntimeError("nbr login did not stick (no account icon after POST)")


def _is_session_bounce(html: str) -> bool:
    return "Session Limit Exceeded" in html


async def _disconnect_stale_sessions(client) -> list[str]:
    """Session-limit heal (measured 2026-11-11): end sessions inactive >72h
    ("last active N days ago" in the block text), always keeping the one
    marked 'Current'. Returns the ended session ids."""
    soup = BeautifulSoup((await client.get(_SESSIONS_PAGE)).text, "html.parser")
    killed: list[str] = []
    for a in soup.select("a[href*='deleteSession']"):
        href = a.get("href", "")
        sid = href.rstrip("/").rsplit("/", 1)[-1]
        if not sid.isdigit():
            continue
        block = ""
        for up in a.parents:
            t = up.get_text(" ", strip=True)
            if "last active" in t:
                block = t
                break
        if "Current" in block:
            continue
        m = re.search(r"last active (\d+) (\w+)", block)
        stale = (m is None
                 or (m.group(2).startswith("day") and int(m.group(1)) >= 3)
                 or (m.group(2).startswith("hour") and int(m.group(1)) >= 72))
        if not stale:
            continue
        await client.get(href)
        killed.append(sid)
        await asyncio.sleep(POLITE_SLEEP)
    return killed


async def fetch_all(urls: list[str]) -> list[tuple[str, str]]:
    """run_source's auth hook: one plain-HTTP login + cookie-jar article
    fetches. Session cookies cached 3 days (~/.querynz/nbr_cookies.json), as
    the Java service did."""
    import json as _json
    import time as _time
    from pathlib import Path

    import httpx

    cache = Path.home() / ".querynz" / "nbr_cookies.json"
    cached: dict[str, str] | None = None
    try:
        d = _json.loads(cache.read_text())
        if _time.time() - d["ts"] < _COOKIE_TTL_S and d["cookies"]:
            cached = d["cookies"]
    except Exception:  # noqa: BLE001 — no/stale cache = fresh login
        pass

    async with httpx.AsyncClient(
            headers={"User-Agent": _BROWSER_UA}, follow_redirects=True,
            timeout=30) as client:
        if cached:
            for k, v in cached.items():
                client.cookies.set(k, v, domain="www.nbr.co.nz")
            home = (await client.get(WWW_BASE_URL)).text
            if not has_account_logged_icon(home):
                cached = None           # session expired — log in again
        if cached is None:
            await _login_http(client)
            cache.parent.mkdir(mode=0o700, exist_ok=True)
            cache.write_text(_json.dumps({
                "ts": _time.time(),
                "cookies": dict(client.cookies)}))
            cache.chmod(0o600)
        out: list[tuple[str, str]] = []
        healed = False
        for url in urls:
            r = await client.get(url)
            if _is_session_bounce(r.text) and not healed:
                # over the 3-session limit: end the stale ones, retry once
                print("  nbr: session-limit bounce — ending stale sessions")
                killed = await _disconnect_stale_sessions(client)
                print(f"  nbr: stale sessions ended: {killed}")
                healed = True
                r = await client.get(url)
                await asyncio.sleep(POLITE_SLEEP)
            if r.status_code == 200 and not _is_session_bounce(r.text):
                out.append((url, r.text))
            else:
                print(f"  nbr: session-limit bounce unresolved, dropped: {url}")
            await asyncio.sleep(POLITE_SLEEP)
    return out


async def fetch_authenticated(urls: list[str], identity: dict[str, str], *,
                              headless: bool = False) -> list[tuple[str, str]]:
    """Port of the NbrContentScraper fetch loop: shared Chromium context with
    the session cookies added once; per page — redirect check + logged-in
    icon check (pages failing either are skipped, as Java marked them
    ContentError)."""
    from playwright.async_api import async_playwright  # lazy — optional dep

    out: list[tuple[str, str]] = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless, proxy=_proxy_config())
        context = await browser.new_context()
        await context.add_cookies([
            {"name": n, "value": identity[n], "domain": _COOKIE_DOMAIN, "path": "/"}
            for n in _COOKIE_NAMES if identity.get(n)])
        page = await context.new_page()
        for url in urls:
            await page.goto(url, wait_until="domcontentloaded", timeout=120_000)
            if page.url != url:
                print(f"  nbr: redirect to no content: {url}")
                continue
            html = await page.content()
            if not has_account_logged_icon(html):
                print(f"  nbr: unable to login (no account icon): {url}")
                continue
            out.append((url, html))
            await asyncio.sleep(base.POLITE_SLEEP)
        await browser.close()
    return out
