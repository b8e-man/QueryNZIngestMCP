#!/usr/bin/env python3
"""Does hansard.parliament.nz boot in Chromium (Radware JS challenge only),
or does it demand an hCaptcha? If it boots: capture the per-debate page
URL pattern from the day index."""
import os
import time

os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "/opt/data/.cache/ms-playwright"
from playwright.sync_api import sync_playwright  # noqa: E402

pw = sync_playwright().start()
browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
ctx = browser.new_context(
    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
page = ctx.new_page()
try:
    page.goto("https://hansard.parliament.nz/", timeout=60000,
              wait_until="domcontentloaded")
    for i in range(10):
        time.sleep(4)
        body = page.content()[:4000]
        text = page.inner_text("body").replace("\n", " ")[:200]
        challenged = ("perfdrive" in body or "captcha" in body.lower()
                      or "hCaptcha" in body)
        print(f"t={4*(i+1)}s challenged={challenged} url={page.url[:80]}")
        print(f"   text: {text}")
        if not challenged and "Loading" not in text:
            break
        if challenged:
            break
    hrefs = page.eval_on_selector_all(
        "a[href]", "els => els.map(e => e.href)")
    print("links:", len(hrefs))
    for h in hrefs[:25]:
        print("  ", h[:120])
except Exception as e:
    print("ERROR", e)
finally:
    browser.close()
    pw.stop()
