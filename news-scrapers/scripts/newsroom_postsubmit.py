"""Newsroom: what does the post-submit page actually say? (error text, notices)"""
import os
from playwright.sync_api import sync_playwright

def load_env(path):
    env = {}
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env

def main():
    env = load_env("/opt/data/evs-credentials/newsscrapers.env")
    em = env.get("NEWSROOM_EMAIL")
    pw = env.get("NEWSROOM_PASSWORD")
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = b.new_context()
        page = ctx.new_page()
        page.goto("https://newsroom.co.nz/wp-login.php", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
        page.evaluate("""(creds) => {
            const set = (el, v) => {
                Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, v);
                el.dispatchEvent(new Event('input', {bubbles: true}));
            };
            set(document.querySelector('#user_login'), creds[0]);
            set(document.querySelector('#user_pass'), creds[1]);
            document.querySelector('#loginform').submit();
        }""", [em, pw])
        page.wait_for_timeout(8000)
        print("URL:", page.url)
        # error/notice blocks
        for sel in ("#login_error", ".message", ".jetpack-sso", "#login form", "body"):
            try:
                txt = page.eval_on_selector(sel, "e => e.innerText.slice(0, 400)")
                if txt.strip():
                    print(f"[{sel}]:", repr(txt[:350]))
            except Exception:
                pass
        b.close()

main()
