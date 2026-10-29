#!/usr/bin/env python3
"""Probe: fetch one NZLII listing page through headless Chromium and dump
the case-link structure. Comparison-source reconnaissance only — no content
is stored."""

import json
import re
import sys
import time

PROXY_F = "/opt/data/beehive-scraper/proxy.json"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"

url = next((a for a in sys.argv[1:] if not a.startswith("--")),
           "https://www.nzlii.org/nz/cases/NZHC/2025/")
use_proxy = "--proxy" in sys.argv

from playwright.sync_api import sync_playwright

proxy = None
if use_proxy:
    import base64
    cfg = json.load(open(PROXY_F))
    proxy = {
        "server": cfg["server"],
        "username": base64.b64decode(cfg["username_b64"]).decode(),
        "password": base64.b64decode(cfg["password_base_b64"]).decode()
        + "_country-nz_session-sprobe_lifetime-10m",
    }

with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True, proxy=proxy,
        args=["--disable-blink-features=AutomationControlled"],
    )
    ctx = browser.new_context(user_agent=UA)
    page = ctx.new_page()
    resp = page.goto(url, timeout=60000)
    print("initial status:", resp.status if resp else 0)
    html = ""
    for i in range(15):
        html = page.content()
        if "Just a moment" not in html and "challenges.cloudflare" not in html:
            break
        page.wait_for_timeout(1000)
    print("after challenge poll:", "PASSED" if "Just a moment" not in html else "STILL CHALLENGED",
          f"({len(html)} bytes)")
    links = re.findall(r'href="(/nz/cases/[^"]+)"', html)
    print(f"case links: {len(links)}")
    for l in links[:15]:
        print("  ", l)
    # pagination hints
    pages = re.findall(r'href="([^"]*(?:page|index\d|start=\d)[^"]*)"', html, re.I)
    print("pagination hints:", pages[:8])
    print("title:", re.search(r"<title>([^<]*)", html).group(1) if re.search(r"<title>([^<]*)", html) else "?")
    browser.close()
