#!/usr/bin/env python3
"""MBIE bulk GETS data files (award notices CSV etc.) — WAF fetch.

mbie.govt.nz serves Incapsula challenges to plain HTTP clients (measured
2026-11-02: 212-byte stub on the data-file URL). The beehive WAF stack
(playwright chromium + IPRoyal NZ residential proxy) is the proven route.

Capture-only: raw bytes to data/external/<filename> + a records.jsonl row
(kind: bulk_dataset). No CSV parsing, no transformation — that is the
gather-phase rule.

Flow: land on the open-data page (solve challenge), then context.request
GET of each data-file URL (inherits the challenge cookies).
"""
import argparse
import base64
import hashlib
import json
import os
import random
import re
import string
import sys
import time
from datetime import datetime, timezone

BASE = "/opt/data/gets-scraper"
EXT = os.path.join(BASE, "data", "external")
RECORDS_F = os.path.join(BASE, "records.jsonl")
DONE_F = os.path.join(BASE, "data", "external_done.jsonl")
PROXY_F = "/opt/data/beehive-scraper/proxy.json"

UA = ("Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 "
      "Firefox/128.0")
LANDING = ("https://www.mbie.govt.nz/cross-government-functions/"
           "new-zealand-government-procurement-and-property/open-data")
FILE_RE = re.compile(r'href="([^"]+\.(?:csv|xlsx|zip)[^"]*)"', re.I)


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def record(url, path, body, ctype, source):
    with open(RECORDS_F, "a") as f:
        f.write(json.dumps({
            "url": url, "kind": "bulk_dataset", "fetched_at": now_iso(),
            "http_status": 200, "sha256": hashlib.sha256(body).hexdigest(),
            "path": path, "bytes": len(body), "content_type": ctype,
            "case_slug": os.path.basename(path), "court": "gets",
            "case_name": os.path.basename(path),
            "discovered_via": source,
        }, ensure_ascii=False) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--time-budget", type=int, default=110)
    args = ap.parse_args()
    t0 = time.time()
    os.makedirs(EXT, exist_ok=True)

    done = set()
    if os.path.exists(DONE_F):
        for line in open(DONE_F):
            try:
                r = json.loads(line)
                if r.get("status") == "ok":
                    done.add(r["url"])
            except ValueError:
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
    fetched = 0
    fails = []
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True, proxy=proxy,
            args=["--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(user_agent=UA)
        page = ctx.new_page()
        try:
            page.goto(LANDING, timeout=45000, wait_until="domcontentloaded")
            time.sleep(6)  # let the Incapsula JS challenge settle
            html = page.content()
        except Exception as e:
            print(f"mbie-bulk: landing failed: {str(e)[:80]}")
            browser.close()
            return 1

        links = []
        for m in FILE_RE.findall(html):
            u = m if m.startswith("http") else "https://www.mbie.govt.nz" + m
            if u not in links:
                links.append(u)
        # always include the known award-notices CSV
        known = ("https://www.mbie.govt.nz/assets/Data-Files/"
                 "NZGPP-GETS-Open-Data/gets-award-notices.csv")
        if known not in links:
            links.append(known)

        for u in links:
            if time.time() - t0 > args.time_budget:
                break
            if u in done:
                continue
            try:
                u_src = "mbie_open_data"
                # real browser navigation: Incapsula 403s ctx.request even
                # with challenge cookies (fingerprint mismatch) — measured
                # 2026-11-02. page.goto carries the full TLS/JS fingerprint.
                body = b""
                status = 0
                for attempt in (0, 1):
                    resp = page.goto(u, timeout=60000,
                                     wait_until="domcontentloaded")
                    time.sleep(4 if attempt == 0 else 8)
                    status = resp.status if resp else 0
                    body = resp.body() if resp else b""
                    if status == 200 and len(body) >= 5000 \
                            and b"Incapsula" not in body[:2000]:
                        break
                if status != 200 or len(body) < 5000 or b"Incapsula" in body[:2000]:
                    # Wayback fallback: static assets are often archived as
                    # real bytes even when the live host WAFs them (IA flaps,
                    # so this also self-heals on the daily cron retry).
                    try:
                        import urllib.request
                        wb = ("https://web.archive.org/web/2id_/" + u)
                        req = urllib.request.Request(
                            wb, headers={"User-Agent": UA})
                        with urllib.request.urlopen(req, timeout=45) as r2:
                            body2 = r2.read()
                        if len(body2) >= 5000 and b"Incapsula" not in body2[:2000]:
                            body, status, u_src = body2, 200, "mbie_open_data+wayback"
                    except Exception:
                        pass
                if status != 200:
                    fails.append(f"{u}: http_{status}")
                    with open(DONE_F, "a") as f:
                        f.write(json.dumps({"url": u,
                                            "status": f"http_{status}"}) + "\n")
                    continue
                if len(body) < 5000 or b"Incapsula" in body[:2000]:
                    fails.append(f"{u}: challenged ({len(body)}B)")
                    continue
                name = u.split("/")[-1].split("?")[0]
                rel = os.path.join("external", name)
                with open(os.path.join(BASE, "data", rel), "wb") as f:
                    f.write(body)
                record(u, rel, body,
                       "application/octet-stream", u_src)
                with open(DONE_F, "a") as f:
                    f.write(json.dumps({"url": u, "status": "ok"}) + "\n")
                fetched += 1
            except Exception as e:
                fails.append(f"{u}: {str(e)[:60]}")
        browser.close()

    print(f"mbie-bulk: fetched={fetched} fails={len(fails)}"
          + (f" ({'; '.join(fails[:3])})" if fails else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
