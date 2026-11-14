"""Probe ODT login DOM: main page + Piano iframe fields + recaptcha presence."""
from playwright.sync_api import sync_playwright

def main():
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = b.new_context()
        page = ctx.new_page()
        page.goto("https://www.odt.co.nz/login", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(6000)
        print("URL:", page.url, "| title:", page.title()[:80])
        html = page.content()
        for marker in ["g-recaptcha", "grecaptcha", "recaptcha/api", "captcha"]:
            print(f"main[{marker}]:", html.lower().count(marker.lower()))
        print("--- iframes ---")
        for f in page.frames:
            print("frame:", f.url[:120])
        for f in page.frames:
            if "piano" in f.url or "identity" in f.url or "login" in f.url:
                try:
                    inputs = f.eval_on_selector_all(
                        "input,button,form",
                        "els => els.map(e => ({tag:e.tagName, type:e.type||'', name:e.name||'', id:e.id||'', cls:(e.className||'').slice(0,60), ph:e.placeholder||'', txt:(e.innerText||'').slice(0,40)}))")
                    print(f"--- inputs in {f.url[:80]} ---")
                    for i in inputs:
                        print(i)
                except Exception as e:
                    print("frame probe err:", e)
        try:
            inputs = page.eval_on_selector_all(
                "input,button,form",
                "els => els.map(e => ({tag:e.tagName, type:e.type||'', name:e.name||'', id:e.id||'', cls:(e.className||'').slice(0,60), ph:e.placeholder||''}))")
            print("--- main inputs ---")
            for i in inputs:
                print(i)
        except Exception as e:
            print("main probe err:", e)
        page.screenshot(path="/opt/data/news-scrapers/ingestion/scripts/odt_login.png", full_page=True)
        b.close()

main()
