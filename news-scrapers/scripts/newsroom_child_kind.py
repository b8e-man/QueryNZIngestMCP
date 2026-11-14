"""Replicate discover()'s child loop exactly: what is each child body, really?"""
import asyncio
import re
import sys

sys.path.insert(0, "/opt/data/news-scrapers/ingestion")
from newsscrapers import newsroom  # noqa: E402


async def main():
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context()
        page = await ctx.new_page()
        resp = await page.goto(newsroom._SITEMAP_INDEX, wait_until="domcontentloaded", timeout=60000)
        body = await resp.text()
        print("index body head:", repr(body[:120]))
        print("index _xml:", bool(re.search(r"<(\w+:)?urlset|<(\w+:)?sitemapindex", body)))
        import xml.etree.ElementTree as ET
        root = ET.fromstring(body.encode())
        kids = [(l.text or "").strip() for l in root.iter(newsroom._SM + "loc") if l.text]
        kids = [k for k in kids if newsroom._SITEMAP_CHILD in k]
        print("children:", kids[:5], "...", len(kids))
        for child in kids[:3]:
            await asyncio.sleep(newsroom.POLITE_SLEEP)
            r = await page.goto(child, wait_until="domcontentloaded", timeout=60000)
            b = await r.text()
            kind = ("challenge" if "Checking your browser" in b
                    else "html-transform" if b.lstrip()[:200].lower().startswith("<!doctype html")
                    else "raw-xml" if "<urlset" in b[:500] else "???")
            print(f"{child}: status={r.status} len={len(b)} kind={kind} head={b[:80]!r}")
        await browser.close()

asyncio.run(main())
