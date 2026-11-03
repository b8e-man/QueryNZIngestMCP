#!/usr/bin/env python3
"""Hansard recon v2: after the Radware challenge solves in Chromium, use
in-page fetch() for everything (challenge cookie applies):
1. /_framework/blazor.boot.json -> main assembly
2. main .wasm -> base64 -> local string hunt for API routes
3. probe discovered API routes in-page"""
import base64
import json
import os
import re
import time

os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "/opt/data/.cache/ms-playwright"
from playwright.sync_api import sync_playwright  # noqa: E402

pw = sync_playwright().start()
browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
ctx = browser.new_context(
    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
page = ctx.new_page()
page.goto("https://hansard.parliament.nz/", timeout=60000,
          wait_until="domcontentloaded")
time.sleep(6)


def infetch(url, as_base64=False):
    js = """async ([u, b64]) => {
        const r = await fetch(u);
        if (b64) {
            const buf = await r.arrayBuffer();
            let bin = ''; const bytes = new Uint8Array(buf);
            for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
            return [r.status, btoa(bin)];
        }
        return [r.status, await r.text()];
    }"""
    return page.evaluate(js, [url, as_base64])


st, txt = infetch("/_framework/blazor.boot.json")
print("boot.json:", st, txt[:80])
boot = json.loads(txt)
main = boot.get("mainAssemblyName")
asms = boot.get("resources", {}).get("assembly", {})
names = [n for n in asms if "Client" in n or "Hansard" in n] or list(asms)[:3]
print("main:", main, "candidates:", names)

U16 = re.compile(rb'(?:[\x20-\x7e]\x00){4,200}')
routes = set()
for n in names:
    st, b64 = infetch(f"/_framework/{n}", as_base64=True)
    body = base64.b64decode(b64)
    print(f"== {n} ({st}, {len(body)}B)")
    for m in U16.finditer(body):
        s = m.group().decode("utf-16-le", errors="replace")
        if re.search(r"^/api/|/download/|debate|speech|sitting", s, re.I):
            if len(s) < 120:
                routes.add(s)
                print("   ", s)

print("\n== API probes (in-page, challenge cookie):")
for r in sorted(routes):
    if r.startswith("/api/"):
        st, txt = infetch(r + ("/" if not r.endswith("/") else "") + "x")
        print(f"  {st} {r}  {txt[:80]}")

browser.close()
pw.stop()
