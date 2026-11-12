"""newsroom.co.nz — port of the Java Newsroom scraper
(ops/scraper-service-standalone .../scraper/newsroom/).

Discovery: single RSS feed (NewsroomRssScraper). RSS is the ONLY discovery
mechanism in the Java design — sitemap crawling was considered and dropped
because Newsroom is subscriber-gated and aggressive crawling risks the
session being blocked.

Content parsing follows NewsroomContentScraper selectors exactly:
title "h1.entry-title.entry-title--with-subtitle" (space-normalised);
date "time.entry-date.published[datetime]" (ISO offset); author
"span.author.vcard a" (profile href not kept — Extracted has no field);
categories "span.cat-links" text lowercased, "posted in" removed,
comma-split. Content is the RAW textContent of "div.entry-content"
(deliberately NOT clean_text/paragraph-joined — the golden samples store
Playwright textContent verbatim, whitespace and all). Articles categorised
"puzzles" return None (Java stored a "content skipped" placeholder row);
likewise the Java "Text content not found" author-only placeholder becomes
None here — a metadata-only stub is not a landable document.

AUTH: in the Java service login was performed ONCE manually in a browser and
the Playwright storageState (cookies + localStorage) was persisted to the DB
by BrowserService and restored per run — login was never automated. The port
now AUTOMATES it (2026-11-11, Arthur's ruling "newsroom: you automate it"):
the login form is plain WordPress (wp-login.php: #user_login, #user_pass,
#wp-submit — no captcha on the form; Cloudflare markers on the page did not
challenge headless). fetch_authenticated() signs in when the saved state
(newsroom_state.json, env NEWSROOM_STORAGE_STATE overrides the path) is
absent or lacks the wordpress_logged_in_ cookie, persists the state, and
restores it per run. NEWSROOM_EMAIL/NEWSROOM_PASSWORD required (same names
as docker/.env.example) — clear error when unconfigured. base.run_source's
plain-httpx path still yields the non-gated articles.
"""
from __future__ import annotations

import asyncio
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime

from bs4 import BeautifulSoup

from . import base

SOURCE = "newsroom.co.nz"
FEEDS = ["https://www.newsroom.co.nz/feed/rss"]  # newest ~15 only - see discover()

# The host serves a HashCash browser-check challenge (403 "Checking your
# browser") to non-browser clients on /feed/ AND /sitemap.xml (measured
# 2026-11-11 under load) — so discovery and fetches run through the browser,
# which passes the challenge. 10s pacing (ARCHIVE's polite rate): the
# challenge signals sensitivity and newsroom publishes ~10/day.
POLITE_SLEEP = 10.0
_SM = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
_SITEMAP_INDEX="https://www.newsroom.co.nz/sitemap.xml"
_SITEMAP_CHILD = "post-sitemap"


async def discover(client) -> list[base.FeedItem]:
    """Browser-walked sitemap discovery, per-URL lastmod as published_at.

    RSS (FEEDS) carries only the newest ~15 items — it cannot serve a
    catch-up window; plain httpx cannot even read the sitemaps (HashCash
    challenge). One browser session walks the sitemap index and every
    post-sitemap child; run_source applies the recency window (--hours) and
    the pre-fetch dedup on top. Reuses the minted login session when
    present; discovery also works logged out (sitemaps are public).
    """
    from playwright.async_api import async_playwright  # lazy — optional dep

    def _xml(page_html: str, url: str) -> "ET.Element | None":
        m = re.search(r"<(\w+:)?urlset|<(\w+:)?sitemapindex", page_html)
        if not m:
            print(f"  newsroom discover: not xml at {url} (challenge page?)")
            return None
        try:
            return ET.fromstring(page_html.encode())
        except ET.ParseError:
            return None

    out: list[base.FeedItem] = []

    async def _fetch_xml(ctx, url: str) -> str:
        # APIRequestContext: raw bytes even when Chromium XSL-transforms the
        # same URL in its DOM (measured 2026-11-11: page.goto response.text()
        # alternates raw/transformed for identical URLs in one session).
        try:
            r = await ctx.request.get(url, timeout=60000)
            return await r.text()
        except Exception:  # noqa: BLE001
            return ""

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        # fresh PUBLIC context: sitemaps need no login and the challenge
        # triggers more on sessioned contexts (measured 2026-11-11)
        ctx = await browser.new_context()
        page = await ctx.new_page()
        xml_src = await _fetch_xml(ctx, _SITEMAP_INDEX)
        root = _xml(xml_src, _SITEMAP_INDEX)
        if root is None:
            # HashCash challenge: its proof-of-work JS reloads AFTER
            # domcontentloaded (~2-4s). Wait for the reload, retry once.
            await page.wait_for_timeout(6000)
            xml_src = await _fetch_xml(ctx, _SITEMAP_INDEX)
            root = _xml(xml_src, _SITEMAP_INDEX)
        children = []
        if root is not None:
            children = [(loc.text or "").strip()
                        for loc in root.iter(_SM + "loc") if loc.text]
        children = [c for c in children if _SITEMAP_CHILD in c]
        for child in children:
            await asyncio.sleep(POLITE_SLEEP)
            c_src = await _fetch_xml(ctx, child)
            c_root = _xml(c_src, child)
            if c_root is None:
                await page.wait_for_timeout(6000)
                c_src = await _fetch_xml(ctx, child)
                c_root = _xml(c_src, child)
            if c_root is None:
                continue
            for u in c_root.iter(_SM + "url"):
                loc = (u.findtext(_SM + "loc") or "").strip()
                lm = (u.findtext(_SM + "lastmod") or "").strip()
                if not loc:
                    continue
                pub = None
                try:
                    pub = datetime.fromisoformat(lm.replace("Z", "+00:00")) if lm else None
                except ValueError:
                    pub = None
                out.append(base.FeedItem(url=loc, published_at=pub))
        await browser.close()
    return out

_TITLE_SEL = "h1.entry-title.entry-title--with-subtitle"
_CONTENT_SEL = "div.entry-content"
_DATE_SEL = "time.entry-date.published"
_AUTHOR_SEL = "span.author.vcard a"
_CATEGORY_SEL = "span.cat-links"

# Java clearIframes() — regex over the *text*, kept for parity (no-op on
# textContent, meaningful if extract() is ever fed markup-bearing strings).
_IFRAME_RE = re.compile(r"(?s)<iframe[^>]*>.*?</iframe>")


class _AllTags(frozenset):
    """bs4 >= 4.13 collapses whitespace-only text nodes to a single \\n unless
    the parent tag is in preserve_whitespace_tags. The goldens store Playwright
    textContent() verbatim (tabs/newlines intact), so preserve everywhere."""

    def __contains__(self, item) -> bool:  # noqa: D105
        return True


def extract(html: str, url: str) -> base.Extracted | None:
    soup = BeautifulSoup(html, "html.parser", preserve_whitespace_tags=_AllTags())

    # Categories first (Java order): textContent of span.cat-links is
    # "Posted inForeign Affairs" -> lowercase, strip "posted in", comma-split.
    categories: list[str] = []
    cat_el = soup.select_one(_CATEGORY_SEL)
    if cat_el is not None:
        cat_text = cat_el.get_text().lower().replace("posted in", "").strip()
        categories = [c.strip() for c in cat_text.split(",") if c.strip()]

    if any(c == "puzzles" for c in categories):
        return None  # Java: "Puzzles article - content skipped" placeholder

    author = None
    author_el = soup.select_one(_AUTHOR_SEL)
    if author_el is not None:
        author = author_el.get_text().strip() or None

    content_el = soup.select_one(_CONTENT_SEL)
    title_el = soup.select_one(_TITLE_SEL)
    if content_el is None or title_el is None:
        # Java stored "Text content not found" when an author was present;
        # nothing landable either way.
        return None

    text = _IFRAME_RE.sub("", content_el.get_text()).strip()
    if not text:
        return None
    title = " ".join(title_el.get_text().split())  # StringUtils.normalizeSpace

    published_at: datetime | None = None
    date_el = soup.select_one(_DATE_SEL)
    if date_el is not None and date_el.get("datetime"):
        try:
            published_at = datetime.fromisoformat(
                date_el["datetime"].strip().replace("Z", "+00:00"))
        except ValueError:
            published_at = None

    return base.Extracted(title=title, text=text, author=author,
                          published_at=published_at, categories=categories)


# --------------------------------------------------------------------------
# Authenticated fetch (BLOCKED without a manually captured subscriber session)
# --------------------------------------------------------------------------

def _credentials() -> tuple[str, str]:
    email = os.environ.get("NEWSROOM_EMAIL")
    password = os.environ.get("NEWSROOM_PASSWORD")
    if not email or not password:
        raise RuntimeError(
            "newsroom credentials not configured: set NEWSROOM_EMAIL and "
            "NEWSROOM_PASSWORD (names as in ops/scraper-service-standalone/"
            "docker/.env.example)")
    return email, password


def _storage_state_path() -> str:
    return os.environ.get("NEWSROOM_STORAGE_STATE",
                          "/opt/data/evs-credentials/newsroom_state.json")


async def _signed_in(context) -> bool:
    """WordPress marks a live session with a wordpress_logged_in_ cookie."""
    for c in await context.cookies():
        if c["name"].startswith("wordpress_logged_in_"):
            return True
    return False


async def _perform_sign_in(page, context) -> None:
    """WordPress form login behind a Jetpack SSO overlay (measured
    2026-11-11): the visible UI is "Log in with WordPress.com" and the
    classic #loginform fields render 0x0 and DISABLED — JS-forcing values
    into them submits an empty password ("The password field is empty.").
    The "Log in with username and password" link reveals the enabled form;
    then it is the plain flow (#user_login/#user_pass -> #wp-submit).
    Persists storage state on the wordpress_logged_in_ cookie; raises when
    the login does not take."""
    em, pw = _credentials()
    state = _storage_state_path()
    await page.goto("https://newsroom.co.nz/wp-login.php",
                    wait_until="domcontentloaded", timeout=60_000)
    try:
        await page.get_by_text(
            "Log in with username and password").first.click(timeout=10_000)
    except Exception:
        pass                                  # form already revealed
    await page.wait_for_selector("#user_login", state="visible", timeout=15_000)
    await page.fill("#user_login", em)
    await page.fill("#user_pass", pw)
    try:
        await page.click("#wp-submit")
    except Exception:
        await page.keyboard.press("Enter")
    await page.wait_for_timeout(6_000)
    if not await _signed_in(context):
        raise RuntimeError(
            "newsroom login did not take (no wordpress_logged_in_ cookie)")
    await context.storage_state(path=state)


async def fetch_authenticated(urls: list[str], *,
                              headless: bool | None = None) -> list[tuple[str, str]]:
    """Fetch article pages with a subscriber session.

    Port of BrowserService.withBrowserPage(): restore storageState (minting
    it via the automated wp-login.php flow when absent), navigate with
    retries, return (url, rendered html) pairs. Requires playwright.
    """
    _credentials()
    state = _storage_state_path()
    if headless is None:
        headless = os.environ.get("NEWSROOM_HEADLESS", "true").lower() != "false"

    from playwright.async_api import async_playwright  # lazy — optional dep

    out: list[tuple[str, str]] = []
    import proxies   # the ONE proxy helper (C207): opt-in, None unless a heavy run asks
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless,
                                           proxy=proxies.playwright_proxy("newsroom"))
        context = await browser.new_context(
            storage_state=state if os.path.exists(state) else None)
        page = await context.new_page()
        if not await _signed_in(context):
            await _perform_sign_in(page, context)
        for url in urls:
            await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            out.append((url, await page.content()))
            await asyncio.sleep(POLITE_SLEEP)   # 10s — challenge-sensitive host
        await browser.close()
    return out


async def fetch_all(urls: list[str]) -> list[tuple[str, str]]:
    """run_source's auth hook — one signed-in browser context for the batch."""
    return await fetch_authenticated(urls)


# B11 ruling 28 (2026-08-24, ARCHIVE_SURVEY_2026-08-24): 16 sub-sitemaps back to 2023-11 (corpus floor 2025-11); gentle by design — subscriber-gated site.
# Walked by newsscrapers.backwalk (resumable, oldest sub-sitemap first).
ARCHIVE = {
    "index": "https://newsroom.co.nz/sitemap.xml",
    "sitemap_re": r"/post-sitemap",
    "polite": 10.0,
}
