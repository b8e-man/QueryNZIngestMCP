#!/usr/bin/env python3
"""JDO reconnaissance: load a JDO page through the browser stack and dump
forms, links, and script/API hints. Nothing stored."""

import json
import re
import sys

PROXY_F = "/opt/data/beehive-scraper/proxy.json"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"

url = next((a for a in sys.argv[1:] if not a.startswith("--")),
           "https://www.justice.govt.nz/courts/decisions/jdo/")

import base64
from playwright.sync_api import sync_playwright

cfg = json.load(open(PROXY_F))
proxy = {
    "server": cfg["server"],
    "username": base64.b64decode(cfg["username_b64"]).decode(),
    "password": base64.b64decode(cfg["password_base_b64"]).decode()
    + "_country-nz_session-sjdo_lifetime-10m",
}

with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True, proxy=proxy,
        args=["--disable-blink-features=AutomationControlled"])
    ctx = browser.new_context(user_agent=UA)
    page = ctx.new_page()
    reqs = []
    page.on("request", lambda r: reqs.append(r.url)
            if any(k in r.url for k in ("api", "search", "json", "query"))
            else None)
    resp = page.goto(url, timeout=60000)
    html = ""
    for _ in range(15):
        html = page.content()
        if "Just a moment" not in html and "challenge" not in html.lower()[:2000]:
            break
        page.wait_for_timeout(1000)
    print("status:", resp.status if resp else 0, "bytes:", len(html))
    print("--- forms:")
    for m in re.findall(r"<form[^>]*>", html)[:6]:
        print("  ", m[:160])
    print("--- input names:")
    names = re.findall(r'<(?:input|select)[^>]*name="([^"]+)"', html)
    print("  ", sorted(set(names))[:30])
    print("--- interesting links:")
    for l in sorted(set(re.findall(r'href="([^"]+)"', html))):
        if re.search(r"search|decision|jdo|rss|feed", l, re.I) \
                and not re.search(r"css|ico|svg|\.js", l, re.I):
            print("  ", l[:130])
    print("--- API-ish requests seen during load:")
    for r in sorted(set(reqs))[:15]:
        print("  ", r[:150])
    print("--- script srcs:")
    for s in sorted(set(re.findall(r'src="([^"]+\.js[^"]*)"', html)))[:10]:
        print("  ", s[:130])
    browser.close()
