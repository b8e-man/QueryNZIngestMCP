#!/usr/bin/env python3
"""Render questions.parliament.nz SPA, search WQ 41284, dump download hrefs.
Also probe selectcommittees.parliament.nz boot + strings."""
import json
import os
import re
import time
import urllib.request

os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "/opt/data/.cache/ms-playwright"
from playwright.sync_api import sync_playwright  # noqa: E402

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# --- 1. SC microsite boot + dll strings ---
def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read(500)

U16 = re.compile(rb'(?:[\x20-\x7e]\x00){4,200}')
st, boot = get("https://selectcommittees.parliament.nz/_framework/blazor.boot.json")
print("SC boot:", st, len(boot))
if st == 200:
    j = json.loads(boot)
    print("  main:", j.get("mainAssemblyName"))
    names = [n for n in j.get("resources", {}).get("assembly", {}) if "Client" in n]
    for n in names:
        st2, body = get(f"https://selectcommittees.parliament.nz/_framework/{n}")
        hits = []
        for m in U16.finditer(body):
            s = m.group().decode("utf-16-le", errors="replace")
            if ("download" in s.lower() or "/api/" in s or "api/data" in s
                    or "attachment" in s.lower()):
                hits.append(s)
        print(f"  {n} ({len(body)}B) interesting strings:")
        for s in sorted(set(hits)):
            print("    ", s[:130])

# --- 2. Render questions SPA ---
print("\n== RENDER questions SPA ==")
pw = sync_playwright().start()
browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
ctx = browser.new_context(
    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
page = ctx.new_page()
page.on("pageerror", lambda e: print("PAGEERROR:", str(e)[:120]))
try:
    page.goto("https://questions.parliament.nz/", timeout=60000,
              wait_until="load")
    for i in range(8):
        time.sleep(4)
        n = page.eval_on_selector_all("a[href], button", "els => els.length")
        txt = page.inner_text("body").replace("\n", " ")[:150]
        print(f"  t={4*(i+1)}s interactive={n} text={txt}")
        if n > 10:
            break
    # try direct question URL patterns
    for u in ("https://questions.parliament.nz/en/written-question/41284-2026",
              "https://questions.parliament.nz/en/pb/written-questions/detail/41284-2026"):
        page.goto(u, timeout=45000, wait_until="load")
        time.sleep(4)
        hrefs = page.eval_on_selector_all(
            "a[href]", "els => els.map(e => e.href + ' | ' + (e.innerText||'').slice(0,40))")
        dl = [h for h in hrefs if "download" in h.lower() or ".pdf" in h.lower()]
        print(f"  {u} -> {len(hrefs)} links, download-ish: {dl[:6]}")
        if dl:
            for h in hrefs[:15]:
                print("    ", h)
except Exception as e:
    print("RENDER ERROR", e)
finally:
    browser.close()
    pw.stop()
