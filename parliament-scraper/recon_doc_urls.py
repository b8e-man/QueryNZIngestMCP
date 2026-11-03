#!/usr/bin/env python3
"""Recon v3: diagnose Blazor render — capture console, page errors, failed
requests, and try longer settle + DOM snapshots."""
import os
import time

os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "/opt/data/.cache/ms-playwright"
from playwright.sync_api import sync_playwright  # noqa: E402

SUB_URL = ("https://www.parliament.nz/en/pb/sc/make-a-submission/document/"
           "54SCMAOC_SCF_E229B214-9A6F-4FE6-CC5C-08DF1467F013/"
           "r%C4%93kohu-wharekauri-shared-redress-bill")


def main():
    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
    ctx = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
    page = ctx.new_page()
    page.on("console", lambda m: print("CONSOLE:", m.type, m.text[:200]))
    page.on("pageerror", lambda e: print("PAGEERROR:", str(e)[:200]))
    page.on("requestfailed",
            lambda r: print("REQFAIL:", r.url[:120], r.failure))

    page.goto(SUB_URL, timeout=60000, wait_until="load")
    for i in range(12):
        time.sleep(5)
        n_links = page.eval_on_selector_all("a[href]", "els => els.length")
        text = page.inner_text("body").replace("\n", " ")[:200]
        print(f"t={5*(i+1)}s links={n_links} text={text}")
        if n_links > 5:
            break

    body = page.content()
    print("HTML len:", len(body))
    print("HTML head:", body[:1500])
    browser.close()
    pw.stop()


if __name__ == "__main__":
    main()
