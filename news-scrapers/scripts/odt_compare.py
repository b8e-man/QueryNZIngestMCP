"""ODT comparison probe: anonymous httpx vs cookie-httpx vs browser-authed.

For 2 fresh article URLs: run odtconz.extract() on each fetch variant,
report body/title lengths only. Decides the cheapest auth path for the module.
Cookies come from odt_state.json; values never printed.
"""
import asyncio
import json
import re
import sys

import httpx

sys.path.insert(0, "/opt/data/news-scrapers/ingestion")
from newsscrapers import base, odtconz  # noqa: E402

STATE = "/opt/data/evs-credentials/odt_state.json"

def state_cookies() -> dict:
    state = json.load(open(STATE))
    jar = {}
    for c in state.get("cookies", []):
        if "odt.co.nz" in c.get("domain", "") or "piano.io" in c.get("domain", ""):
            jar[c["name"]] = c["value"]
    return jar

async def discover_urls(n=2):
    async with httpx.AsyncClient(timeout=60, follow_redirects=True,
                                 headers={"User-Agent": base.USER_AGENT} if hasattr(base, "USER_AGENT") else {}) as client:
        items = await odtconz.discover(client)
    return [i.url for i in items[:n]]

def try_extract(html, url, label):
    ex = odtconz.extract(html, url)
    if ex is None:
        print(f"  {label}: extract() -> None (thin/empty)")
    else:
        print(f"  {label}: title={len(ex.title)} body={len(ex.text)} author={ex.author!r} date={ex.published_at}")
        print(f"    body head: {ex.text[:120]!r}")

async def main():
    urls = await discover_urls(2)
    print("fresh urls:", urls)
    jar = state_cookies()
    print("cookie jar size:", len(jar))

    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        for url in urls:
            print("==", url)
            r = await client.get(url)
            print("  anon httpx:", r.status_code, len(r.text))
            try_extract(r.text, url, "anon")

    async with httpx.AsyncClient(timeout=60, follow_redirects=True, cookies=jar) as client:
        for url in urls:
            r = await client.get(url)
            print("  cookie httpx:", r.status_code, len(r.text))
            try_extract(r.text, url, "cookie")

    # browser-authed variant
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = b.new_context(storage_state=STATE, user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
        page = ctx.new_page()
        for url in urls:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(4000)
            html = page.content()
            print("  browser:", len(html))
            try_extract(html, url, "browser")
        b.close()

asyncio.run(main())
