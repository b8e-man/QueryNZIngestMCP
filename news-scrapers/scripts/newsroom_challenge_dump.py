"""What does the browser ACTUALLY see on the sitemap route? Full state dump."""
import asyncio
import sys

sys.path.insert(0, "/opt/data/news-scrapers/ingestion")


async def main():
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context()
        page = await ctx.new_page()
        await page.goto("https://newsroom.co.nz" + "/sitemap.xml",
                        wait_until="domcontentloaded", timeout=60000)
        for t in (2, 6, 12):
            await page.wait_for_timeout(t * 1000 - (0 if t == 2 else {6: 2, 12: 6}[t]) * 1000)
            url = page.url
            title = await page.title()
            body = await page.eval_on_selector("body", "e => e.innerText.slice(0, 300)")
            ser = await page.evaluate("new XMLSerializer().serializeToString(document)")
            print(f"--- t+{t}s url={url[:60]} title={title[:40]!r}")
            print("   body:", repr(body[:150]))
            print("   serialized head:", repr(ser[:150]))
        # cookies the challenge set
        names = [c["name"] for c in await ctx.cookies()]
        print("cookies:", names)
        await browser.close()

asyncio.run(main())
