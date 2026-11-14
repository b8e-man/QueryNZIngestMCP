"""Newsroom: run the module's OWN _perform_sign_in flow, capture post-submit error text."""
import asyncio
import os
import sys

sys.path.insert(0, "/opt/data/news-scrapers/ingestion")
os.environ.setdefault("NEWSROOM_STORAGE_STATE", "/tmp/nr_diag_state.json")
from newsscrapers import newsroom  # noqa: E402


async def main():
    from playwright.async_api import async_playwright
    em, pw = newsroom._credentials()
    print("creds loaded: email_len", len(em), "pw_len", len(pw))
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True)
        ctx = await b.new_context()
        page = await ctx.new_page()
        await page.goto("https://newsroom.co.nz/wp-login.php",
                        wait_until="domcontentloaded", timeout=60_000)
        # the reveal link
        try:
            link = page.get_by_text("Log in with username and password").first
            print("reveal link visible:", await link.is_visible())
            await link.click(timeout=10_000)
            print("reveal link clicked")
        except Exception as e:
            print("reveal link err:", type(e).__name__, e)
        try:
            await page.wait_for_selector("#user_login", state="visible", timeout=10_000)
            print("#user_login now visible")
        except Exception as e:
            print("#user_login still hidden:", type(e).__name__)
        # are the fields enabled?
        state = await page.evaluate("""() => {
            const log = document.querySelector('#user_login');
            const pwd = document.querySelector('#user_pass');
            const r = pwd ? pwd.getBoundingClientRect() : null;
            return {log_disabled: log ? log.disabled : null,
                    pwd_disabled: pwd ? pwd.disabled : null,
                    pwd_w: r ? r.width : null, pwd_h: r ? r.height : null};
        }""")
        print("field state:", state)
        await page.fill("#user_login", em)
        await page.fill("#user_pass", pw)
        await page.click("#wp-submit")
        await page.wait_for_timeout(8000)
        print("post-submit URL:", page.url)
        for sel in ("#login_error", ".message", "body"):
            try:
                txt = await page.eval_on_selector(sel, "e => e.innerText.slice(0, 300)")
                if txt.strip():
                    print(f"[{sel}]:", repr(txt[:280]))
            except Exception:
                pass
        cookies = {c["name"]: c["value"] for c in await ctx.cookies()}
        print("auth cookies:", [n for n in cookies if "wordpress" in n])
        await b.close()

asyncio.run(main())
