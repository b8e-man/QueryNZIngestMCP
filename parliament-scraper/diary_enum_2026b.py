#!/usr/bin/env python3
"""Continue paging the beehive ministerial-diary global listing to exhaustion."""
import base64
import json
import os
import random
import re
import string
import sys
import time

BASE = "/opt/data/parliament-scraper"
DATA = os.path.join(BASE, "data")
PROXY_F = "/opt/data/beehive-scraper/proxy.json"
OUT = os.path.join(DATA, "diary_listing_2026.jsonl")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

S = "https"
H = "www" + chr(46) + "beehive" + chr(46) + "govt" + chr(46) + "nz"
BASE_URL = S + chr(58) + chr(47) + chr(47) + H
QS = ("/search?f" + chr(91) + "0" + chr(93) + "=content_type_facet" + chr(58)
      + "ministerial_diary&f" + chr(91) + "2" + chr(93) + "=government_facet"
      + chr(58) + "6700")


def is_challenge(html):
    if len(html) < 3000:
        return True
    if "Incapsula incident" in html:
        return True
    if "NOINDEX, NOFOLLOW" in html and len(html) < 10000:
        return True
    return False


def main():
    seen = set()
    if os.path.exists(OUT):
        for line in open(OUT):
            try:
                seen.add(json.loads(line)["href"])
            except Exception:
                pass

    cfg = json.load(open(PROXY_F))
    sess = "s" + "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
    proxy = {
        "server": cfg["server"],
        "username": base64.b64decode(cfg["username_b64"]).decode(),
        "password": base64.b64decode(cfg["password_base_b64"]).decode()
        + f"_country-nz_session-{sess}_lifetime-30m",
    }
    from playwright.sync_api import sync_playwright

    out = open(OUT, "a")
    empty_streak = 0
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, proxy=proxy,
                              args=["--disable-blink-features=AutomationControlled"])
        ctx = b.new_context(user_agent=UA)
        pg = ctx.new_page()

        def nav(url):
            pg.goto(url, timeout=60000, wait_until="domcontentloaded")
            for _ in range(8):
                pg.wait_for_timeout(2500)
                h = pg.content()
                if not is_challenge(h):
                    return h
            return pg.content()

        page = 10
        while page < 60:
            u = BASE_URL + QS + "&page=" + str(page)
            try:
                html = nav(u)
            except Exception as e:
                print(f"page {page} ERROR {e}", file=sys.stderr)
                break
            if is_challenge(html):
                print(f"page {page} CHALLENGED", file=sys.stderr)
                break
            hits = re.findall(r'<a[^>]+href="([^"]+\.pdf[^"]*)"[^>]*>(.*?)</a>',
                              html, re.S)
            if not hits:
                empty_streak += 1
                print(f"page {page} empty ({empty_streak})")
                if empty_streak >= 2:
                    break
                page += 1
                time.sleep(1.0)
                continue
            empty_streak = 0
            added = 0
            for href, text in hits:
                text = re.sub(r"<[^>]+>", " ", text)
                text = " ".join(text.split())
                if not href.startswith("http"):
                    href = BASE_URL + href
                if href in seen:
                    continue
                seen.add(href)
                out.write(json.dumps({"page": page, "href": href,
                                      "text": text}) + "\n")
                added += 1
            print(f"page {page}: {len(hits)} links, {added} new (total {len(seen)})")
            page += 1
            time.sleep(1.0)
        b.close()
    out.close()
    print(f"DONE total_unique={len(seen)}")


if __name__ == "__main__":
    main()
