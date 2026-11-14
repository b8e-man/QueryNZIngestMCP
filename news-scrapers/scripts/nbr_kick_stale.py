"""NBR: disconnect the STALE sessions (>72h inactive, never 'Current'), then
fetch a real article and verify the body serves. Remedies the 'Session Limit
Exceeded' bounce documented 2026-11-11."""
import asyncio
import json
import re
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

        # land on the sessions page (any article bounces there now)
        await page.goto("https://www.nbr.co.nz/my-account/sessions/",
                        wait_until="domcontentloaded", timeout=90000)
        await page.wait_for_timeout(3000)

        # each session block: link href has deleteSession/<id>; block text says
        # "Chrome on Windows 10. <ip>, last active X..." and "Current" if ours.
        blocks = await page.eval_on_selector_all(
            "a[href*='deleteSession']",
            """els => els.map(a => {
                let n = a.closest('div, li, tr');
                let t = (n ? n.innerText : '').replace(/\\s+/g, ' ').slice(0, 160);
                return {href: a.href, block: t};
            })""")
        print("session blocks:")
        killed = []
        for b in blocks:
            print(" ", b["href"].split("/")[-1], "|", b["block"][:110])
            if "Current" in b["block"]:
                print("    -> ours, keeping")
                continue
            m = re.search(r"last active (\d+) (day|hour|minute)", b["block"])
            stale = (not m) or (m.group(2) == "day" and int(m.group(1)) >= 3)
            if stale:
                r = await page.goto(b["href"], wait_until="domcontentloaded", timeout=60000)
                print("    -> disconnected:", r.status if r else "?")
                killed.append(b["href"].split("/")[-1])
            else:
                print("    -> recent (<3d), keeping")
        print("killed:", killed)

        # decisive: a real article now serves its body
        await page.goto(ARTICLE, wait_until="domcontentloaded", timeout=90000)
        await page.wait_for_timeout(4000)
        print("final URL:", page.url)
        txt = await page.eval_on_selector("body", "e => e.innerText")
        i = txt.find("Lucidome")
        print("body len:", len(txt), "| Lucidome at:", i)
        if i >= 0:
            print("body snippet:", repr(txt[i:i+240]))
        # also: plain httpx with the same cookies now?
        await browser.close()

    import httpx
    async with httpx.AsyncClient(headers={"User-Agent": nbr._BROWSER_UA},
                                 follow_redirects=True, timeout=60,
                                 cookies=d["cookies"]) as client:
        r = await client.get(ARTICLE)
        ex = nbr.extract(r.text, ARTICLE)
        print("httpx status:", r.status_code, "| final path:", r.url.path)
        print("extract:", None if ex is None else f"title={len(ex.title)} text={len(ex.text)}")
        if ex and ex.text:
            print("text head:", repr(ex.text[:150]))

asyncio.run(main())
