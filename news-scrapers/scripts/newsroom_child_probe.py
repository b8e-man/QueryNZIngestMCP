"""What does a child sitemap URL actually return? status + body head + final url."""
import asyncio


async def main():
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context()
        page = await ctx.new_page()
        for u in ("/post-sitemap2.xml", "/post-sitemap.xml", "/post-sitemap1.xml"):
            resp = await page.goto("https://newsroom.co.nz" + u,
                                   wait_until="domcontentloaded", timeout=60000)
            body = await resp.text()
            print("== req", u, "-> final", page.url[-40:], "status", resp.status, "len", len(body))
            print("   head:", repr(body[:200]))
        await browser.close()

asyncio.run(main())
