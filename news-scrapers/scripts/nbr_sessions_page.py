"""NBR: read the /my-account/sessions/ page we get bounced to — what is it telling us?"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, "/opt/data/news-scrapers/ingestion")
from newsscrapers import nbr  # noqa: E402

ARTICLE = "https://www.nbr.co.nz/primary-industries/lucidome-bio-raises-9m-for-livestock-methane-vaccine/"


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
        resp = await page.goto(ARTICLE, wait_until="domcontentloaded", timeout=90000)
        await page.wait_for_timeout(4000)
        print("final URL:", page.url)
        print("article status:", resp.status if resp else "?")
        txt = await page.eval_on_selector("body", "e => e.innerText")
        # skip the nav menu: print from the first non-menu content
        print("=== sessions page text ===")
        print(txt[:2500])
        # any buttons/links to revoke sessions?
        links = await page.eval_on_selector_all(
            "a, button",
            "els => els.map(e => ({t: (e.innerText||'').trim().slice(0,60), h: e.href||''})).filter(x => x.t)")
        print("=== interactive elements ===")
        for l in links:
            if any(k in (l['t'] + l['h']).lower() for k in ("session", "log", "revoke", "remove", "end", "kick", "device")):
                print(" ", l)
        await browser.close()

asyncio.run(main())
