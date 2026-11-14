"""ODT login via the Piano identity iframe. Creds from odt.env only.

One attempt. On failure: report and HOLD (house rule).
Signed-in evidence: Piano auth cookies + a protected page rendering subscriber chrome.
"""
import os
import sys
from playwright.sync_api import sync_playwright

ENV = "/opt/data/evs-credentials/odt.env"

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
    if not email or not password:
        print("FAIL: no creds in odt.env keys:", sorted(env.keys()))
        sys.exit(1)
    print("creds loaded: email_len", len(email), "pw_len", len(password))

    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = b.new_context(user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
        page = ctx.new_page()
        page.goto("https://www.odt.co.nz/login", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)

        # find the piano identity frame
        frame = None
        for f in page.frames:
            if "piano.io/id" in f.url:
                frame = f
                break
        if frame is None:
            print("FAIL: piano identity frame never appeared")
            b.close()
            sys.exit(1)
        print("frame found:", frame.url[:80])

        frame.wait_for_selector("input[name=email]", timeout=15000)
        frame.fill("input[name=email]", email)
        # password input has no name; take the password-typed input
        frame.fill("input[type=password]", password)
        # capture response after submit to see auth result
        try:
            with page.expect_response(lambda r: "login" in r.url or "auth" in r.url or "token" in r.url, timeout=20000) as ri:
                frame.click("button[type=submit]")
            resp = ri.value
            print("submit response:", resp.status, resp.url[:100])
        except Exception as e:
            print("submit: no captured response:", type(e).__name__)
        page.wait_for_timeout(7000)

        # signed-in evidence: cookies + page state
        cookies = ctx.cookies()
        authish = [c["name"] for c in cookies if any(t in c["name"].lower() for t in ("token", "auth", "uid", "pid", "piano", "session", "sub"))]
        print("cookies:", authish)
        print("post-login URL:", page.url)
        # did the frame change (e.g. to signed-in view / otp / error)?
        for f in page.frames:
            if "piano.io/id" in f.url:
                try:
                    txt = f.eval_on_selector("body", "e => e.innerText.slice(0, 300)")
                    print("frame body:", repr(txt))
                except Exception as e:
                    print("frame body err:", e)
        # any error/notice in main page
        try:
            notice = page.eval_on_selector_all("[class*=error],[class*=alert],[class*=notice]", "els => els.map(e => e.innerText.slice(0,120)).filter(Boolean)")
            print("notices:", notice[:5])
        except Exception:
            pass
        page.screenshot(path="/opt/data/news-scrapers/ingestion/scripts/odt_after_submit.png", full_page=True)

        # decisive test: a paywalled article page renders full body when signed in
        page.goto("https://www.odt.co.nz/in-depth", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
        links = page.eval_on_selector_all("a[href*='/star/'],a[href*='/news/']", "els => els.map(e => e.href).filter(h => h.endsWith('.html') || /\\/\\d+\\//.test(h)).slice(0,5)")
        print("sample article links:", links[:3])
        b.close()
        print("DONE")

main()
