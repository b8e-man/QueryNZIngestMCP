"""NBR: what does the rendered article page actually say? Full innerText +
every network response, longer wait."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, "/opt/data/news-scrapers/ingestion")
from newsscrapers import nbr  # noqa: E402

URL = "https://www.nbr.co.nz/primary-industries/lucidome-bio-raises-9m-for-livestock-methane-vaccine/"


async def main():
    from playwright.async_api import async_playwright
    d = json.loads((Path.home() / ".querynz" / "nbr_cookies.json").read_text())
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(user_agent=nbr._BROWSER_UA)
        await ctx.add_cookies([
            {"name": k, "value": v, "domain": "www.nbr.co.nz", "path": "/"}
            for k, v in d["cookies"].items()])
        page = await ctx.new_page()
        resps = []
        page.on("response", lambda r: resps.append((r.status, r.request.resource_type, r.url[:110])))
        await page.goto(URL, wait_until="networkidle", timeout=90000)
        await page.wait_for_timeout(10000)
        txt = await page.eval_on_selector("body", "e => e.innerText")
        print("=== rendered innerText (full) ===")
        print(txt)
        print("=== network responses ===")
        for status, rtype, url in resps:
            if rtype in ("xhr", "fetch", "document", "script"):
                print(f"  {status} {rtype:8s} {url}")
        await browser.close()

asyncio.run(main())
