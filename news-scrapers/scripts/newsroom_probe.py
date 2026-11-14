"""Probe newsroom.co.nz login DOM: forms, fields, captcha, iframe vendors."""
from playwright.sync_api import sync_playwright

def main():
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = b.new_context()
        page = ctx.new_page()
        for url in ("https://newsroom.co.nz/login/",
                    "https://newsroom.co.nz/wp-login.php",
                    "https://newsroom.co.nz/account/"):
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(4000)
            except Exception as e:
                print("==", url, "NAV ERR", type(e).__name__)
                continue
            print("==", url, "->", page.url, "|", page.title()[:60])
            html = page.content()
            for marker in ["g-recaptcha", "grecaptcha", "captcha", "cloudflare", "turnstile", "hcaptcha"]:
                if marker in html.lower():
                    print("   marker:", marker)
            for f in page.frames:
                if f != page.main_frame:
                    print("   frame:", f.url[:100])
            try:
                inputs = page.eval_on_selector_all(
                    "input,button,form",
                    "els => els.map(e => ({tag:e.tagName, type:e.type||'', name:e.name||'', id:e.id||'', cls:(e.className||'').slice(0,50), ph:e.placeholder||''}))")
                for i in inputs[:12]:
                    print("   ", i)
            except Exception as e:
                print("   probe err:", e)
        b.close()

main()
