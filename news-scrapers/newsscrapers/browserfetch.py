"""Shared Playwright browser fetch — for sources behind Incapsula/anti-bot
(beehive.govt.nz). One Chromium context (real UA), used for the discovery page
and every article. WSL-safe launch flags (--disable-dev-shm-usage or Chromium
SIGTRAPs on the small default /dev/shm).

Optional dependency: playwright + `playwright install chromium`. Callers wrap
usage in run_source's fetch_all hook, which already falls back to plain httpx
on any failure.
"""
from __future__ import annotations

import asyncio

_LAUNCH_ARGS = ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
# Incapsula serves a tiny JS-challenge shell first; the real page follows.
# A CHALLENGE SHELL, WHOEVER SERVES IT (C215, 2026-10-08). This was one marker
# — Incapsula's — and the guard below also broke out whenever the page exceeded
# 20,000 bytes. Cloudflare's "Just a moment..." interstitial is **29,045 bytes
# and carries no content at all**, so it passed both tests and was handed to the
# extractor, which returned nothing, which the lane counted as THIN.
#
# That conflation is the real defect: `thin` says the publisher published little,
# `challenged` says WE WERE REFUSED. Measured on stoppress.co.nz — the first page
# of a batch renders fully (258 KB, 3,834 chars) and every page after it comes
# back as the 29 KB interstitial — so an archive walk reported 19 of 20 pages
# thin and the refusal was invisible. SIZE IS NOT A SIGNAL: an interstitial is
# mostly inlined CSS and script, and a thin real article is small.
#
# A challenged page is a FAILED READ and is never returned as content. We wait
# for a JS challenge to resolve itself, which is what any browser does; we do
# not and will not defeat one.
_CHALLENGE_MARKERS = (
    "_Incapsula_Resource",                  # Imperva/Incapsula
    "/cdn-cgi/challenge-platform/",         # Cloudflare's challenge script path
    "cf-chl-",                              # Cloudflare challenge element ids
    "Just a moment...",                     # its visible title
)


def is_challenge(html: str) -> bool:
    """True when this body is an interstitial rather than the page asked for."""
    return any(m in (html or "") for m in _CHALLENGE_MARKERS)


async def fetch_raw(urls: list[str], *, timeout_ms: int = 60_000,
                    source: str | None = None) -> list[tuple[str, str]]:
    """Raw response bodies through the headless browser — for feeds/pages
    behind WAF shells, where page.content() delivers Chromium's escaped
    XML-viewer output instead of tags (measured on ecan, 2026-11-09). ONE
    context per call: a plain request first (the request API shares the
    context's cookies); where the shell answers, navigate to solve the
    challenge and re-read the raw body. The solved cookie carries to the next
    URL in the list — feed and articles share one session. A challenge that
    will not solve reads as refused (never appended)."""
    if source is None:
        from urllib.parse import urlparse
        source = urlparse(urls[0]).hostname if urls else None
    import proxies   # the ONE proxy helper (C207)
    from playwright.async_api import async_playwright  # lazy — optional dep

    out: list[tuple[str, str]] = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=_LAUNCH_ARGS,
                                           proxy=proxies.playwright_proxy(source))
        ctx = await browser.new_context(user_agent=_UA)
        page = await ctx.new_page()
        try:
            for url in urls:
                try:
                    r = await ctx.request.get(url, timeout=timeout_ms)
                    body = await r.text()
                    if is_challenge(body):
                        await page.goto(url, wait_until="domcontentloaded",
                                        timeout=timeout_ms)
                        for _ in range(6):
                            html = await page.content()
                            if not is_challenge(html):
                                break
                            await page.wait_for_timeout(2000)
                        else:
                            print(f"  CHALLENGED (a challenged read is a "
                                  f"failed read): {url}")
                            continue
                        r = await ctx.request.get(url, timeout=timeout_ms)
                        body = await r.text()
                        if is_challenge(body):
                            print(f"  CHALLENGED (a challenged read is a "
                                  f"failed read): {url}")
                            continue
                    out.append((url, body))
                except Exception as e:  # noqa: BLE001 — one bad page ≠ dead run
                    print(f"  browser fetch error {url}: {type(e).__name__}: {e}")
                await asyncio.sleep(1.0)
        finally:
            await browser.close()
    return out


async def render_all(urls: list[str], *, settle_ms: int = 1500,
                     timeout_ms: int = 60_000,
                     source: str | None = None) -> list[tuple[str, str]]:
    """Fetch each URL through a headless browser; returns (url, html). Retries
    past the Incapsula challenge shell (up to ~12s per URL). `source` names
    the scraper for the proxy helper's per-source stickiness (DECISIONS 170);
    the first URL's host when the caller does not say."""
    if source is None and urls:
        from urllib.parse import urlparse
        source = urlparse(urls[0]).hostname
    from playwright.async_api import async_playwright  # lazy — optional dep

    out: list[tuple[str, str]] = []
    challenged: list[str] = []
    import proxies   # the ONE proxy helper (C207): opt-in, None unless a heavy run asks
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=_LAUNCH_ARGS,
                                           proxy=proxies.playwright_proxy(source))
        ctx = await browser.new_context(user_agent=_UA)
        page = await ctx.new_page()
        try:
            for url in urls:
                try:
                    await page.goto(url, wait_until="domcontentloaded",
                                    timeout=timeout_ms)
                    for _ in range(6):
                        html = await page.content()
                        if not is_challenge(html):
                            break
                        await page.wait_for_timeout(2000)
                    await page.wait_for_timeout(settle_ms)
                    html = await page.content()
                    if is_challenge(html):
                        # REFUSED, and recorded as refused. Never appended: a
                        # challenge handed to an extractor becomes a `thin`
                        # count, which reads as the publisher's fault.
                        challenged.append(url)
                        print(f"  CHALLENGED (a challenged read is a failed "
                              f"read): {url}")
                    else:
                        out.append((url, html))
                except Exception as e:  # noqa: BLE001 — one bad page ≠ dead run
                    print(f"  browser fetch error {url}: {type(e).__name__}: {e}")
                await asyncio.sleep(1.0)
        finally:
            await browser.close()
    if challenged:
        print(f"  {len(challenged)} of {len(urls)} url(s) were CHALLENGED and "
              f"not read — the host is refusing us past the first page; a lane "
              f"that keeps asking is one that should be marked blocked:antibot")
    return out
