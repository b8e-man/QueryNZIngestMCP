"""ODT login + DECISIVE verification + storage_state save. One pass."""
import json
from playwright.sync_api import sync_playwright

ENV = "/opt/data/evs-credentials/odt.env"
STATE = "/opt/data/evs-credentials/odt_state.json"

def load_env(path):
    env = {}
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip().removeprefix("export ").strip()] = v.strip().strip('"').strip("'")
    return env

def main():
    env = load_env(ENV)
    email = env.get("ODT_EMAIL") or env.get("EMAIL")
    password = env.get("ODT_PASSWORD") or env.get("PASSWORD")

    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = b.new_context(user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
        page = ctx.new_page()
        page.goto("https://www.odt.co.nz/login", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)
        frame = next((f for f in page.frames if "piano.io/id" in f.url), None)
        if frame is None:
            print("FAIL: no piano frame"); b.close(); return
        frame.wait_for_selector("input[name=email]", timeout=15000)
        frame.fill("input[name=email]", email)
        frame.fill("input[type=password]", password)
        frame.click("button[type=submit]")
        page.wait_for_timeout(8000)

        # 1) piano frame state after submit
        for f in page.frames:
            if "piano.io" in f.url:
                try:
                    txt = f.eval_on_selector("body", "e => e.innerText.slice(0, 400)")
                    print("PIANO FRAME BODY:", repr(txt))
                except Exception as e:
                    print("frame body err:", e)

        # 2) reload /login — signed-in users usually get redirected or shown account chrome
        page.goto("https://www.odt.co.nz/login", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)
        body_txt = page.eval_on_selector("body", "e => e.innerText.slice(0, 500)")
        print("LOGIN PAGE BODY:", repr(body_txt[:300]))
        for f in page.frames:
            if "piano.io/id" in f.url:
                try:
                    txt = f.eval_on_selector("body", "e => e.innerText.slice(0, 400)")
                    print("LOGIN2 FRAME BODY:", repr(txt))
                except Exception as e:
                    print("login2 frame err:", e)

        # 3) cookie dump (names + lengths only) — look for piano auth token cookie
        for c in ctx.cookies():
            print("COOKIE:", c["name"], "len", len(c.get("value", "")), "domain", c["domain"])

        # 4) decisive: open a news article, look for paywall vs full body
        page.goto("https://www.odt.co.nz/latest", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
        links = page.eval_on_selector_all("a", "els => els.map(e => e.href).filter(h => /odt\\.co\\.nz\\/(star|news|business|opinion)\\//.test(h) && h.length > 40).slice(0, 20)")
        links = list(dict.fromkeys(links))
        print("article candidates:", len(links))
        if links:
            page.goto(links[0], wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(5000)
            art = page.eval_on_selector("body", "e => e.innerText.slice(0, 800)")
            print("ARTICLE BODY:", repr(art[:500]))
            html = page.content()
            for marker in ["subscribe", "paywall", "Piano", "Sign in to", "premium"]:
                print(f"marker[{marker}]:", html.lower().count(marker.lower()))

        ctx.storage_state(path=STATE)
        print("storage state saved ->", STATE)
        b.close()

main()
