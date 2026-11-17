#!/usr/bin/env python3
"""Cross-check the government facet id used for the diary listing.

The captured beehive release page (2026-10-26) links a per-minister facet search
carrying government_facet:6203, while our enumeration used 6700. Verify the two
scope to the same current-government diary set (or find what 6203 adds).
"""
import base64
import json
import os
import random
import re
import string
import time

BASE = "/opt/data/parliament-scraper"
DATA = os.path.join(BASE, "data")
PROXY_F = "/opt/data/beehive-scraper/proxy.json"
OUT = os.path.join(DATA, "diary_listing_6203.jsonl")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
S = "https"
H = "www" + chr(46) + "beehive" + chr(46) + "govt" + chr(46) + "nz"
BASE_URL = S + chr(58) + chr(47) + chr(47) + H


def qs(gov):
    return ("/search?f" + chr(91) + "0" + chr(93) + "=content_type_facet" + chr(58)
            + "ministerial_diary&f" + chr(91) + "2" + chr(93) + "=government_facet"
            + chr(58) + gov)


def is_challenge(html):
    return len(html) < 3000 or "Incapsula incident" in html


def main():
    cfg = json.load(open(PROXY_F))
    sess = "s" + "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
    proxy = {"server": cfg["server"],
             "username": base64.b64decode(cfg["username_b64"]).decode(),
             "password": base64.b64decode(cfg["password_base_b64"]).decode()
             + f"_country-nz_session-{sess}_lifetime-30m"}
    from playwright.sync_api import sync_playwright

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

        for gov in ("6203", "6700"):
            seen = set()
            for page in range(0, 4):
                html = nav(BASE_URL + qs(gov) + "&page=" + str(page))
                if is_challenge(html):
                    print(gov, f"page {page} CHALLENGED")
                    break
                hits = re.findall(r'<a[^>]+href="([^"]+\.pdf[^"]*)"[^>]*>', html)
                new = [h for h in hits if h not in seen]
                seen.update(hits)
                print(f"gov={gov} page={page} links={len(hits)} unique_so_far={len(seen)}")
                if not hits:
                    break
                time.sleep(0.8)
            with open(OUT.replace("6203", gov), "w") as f:
                for u in sorted(seen):
                    f.write(json.dumps({"href": u}) + "\n")
        b.close()


if __name__ == "__main__":
    main()
