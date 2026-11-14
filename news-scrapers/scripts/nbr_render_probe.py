"""NBR: render one article in Chromium with the session, capture network —
which request carries the body? Also verify the body renders at all."""
import asyncio
import json
import re
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
        hits = []

        async def on_response(resp):
            try:
                ct = resp.headers.get("content-type", "")
                if "json" in ct or "html" in ct:
                    body = await resp.text()
                    if "Lucidome" in body or "methane" in body:
                        hits.append((resp.url, ct, len(body), body[:0]))
            except Exception:
                pass

        page.on("response", lambda r: asyncio.ensure_future(on_response(r)))
        await page.goto(URL, wait_until="domcontentloaded", timeout=90000)
        await page.wait_for_timeout(6000)
        txt = await page.eval_on_selector("body", "e => e.innerText")
        print("rendered body len:", len(txt))
        i = txt.find("Lucidome")
        print("Lucidome at:", i)
        if i >= 0:
            print("rendered snippet:", repr(txt[i:i+300]))
        print("account icon:", nbr.has_account_logged_icon(await page.content()))
        print("--- network hits carrying body text ---")
        for url, ct, ln, _ in hits[:10]:
            print(f"  {ln:7d} {ct[:30]:30s} {url[:110]}")
        await browser.close()

asyncio.run(main())
