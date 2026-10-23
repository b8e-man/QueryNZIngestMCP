#!/usr/bin/env python3
"""Beehive Tier-2 body fetcher — drains a URL queue through the IPRoyal
residential proxy with headless chromium.

Plain HTTP clients (curl/urllib) get the Incapsula JS challenge stub from
every IP including residential ones; a real browser passes (the JS challenge
auto-solves in ~2-5s and the real page is served). The VPS's own IP is
challenged even in a browser — the proxy is required.

Usage:
  beehive_bodyfetch.py                          # forward queue, 12/run
  beehive_bodyfetch.py --queue backfill_queue.jsonl --limit 60

Creds: base64 fragments in /opt/data/beehive-scraper/proxy.json (600).
The IPRoyal session suffix (country-nz_session-<random>_lifetime-30m) is
generated fresh per run — reusing one session ID burns it out.

Detection note: real Incapsula-fronted pages ALSO reference
/_Incapsula_Resource scripts, so that string alone is NOT a challenge
marker. The stub is identified by its tiny size + noindex meta / incident
page markers.

Retry semantics: done.jsonl status=="ok" is final; failed/challenged entries
are retried on later runs (transient network drops, burned proxy exits).

Exit semantics (cron no_agent): silent + exit 0 on success (or nothing to
do); stderr + exit 1 on failure/challenge so the scheduler alerts.

Bandwidth: every run appends one line to logs/bodyfetch_stats.log with pages
and bytes transferred (images/fonts/media/stylesheet blocked; JS needed for
the challenge is cached across pages in the same browser context).
"""

import argparse
import base64
import hashlib
import json
import os
import random
import string
import sys
import time
from datetime import datetime, timezone

BASE = "/opt/data/beehive-scraper"
DONE_F = os.path.join(BASE, "done.jsonl")
PAGES = os.path.join(BASE, "data", "pages")
PROXY_F = os.path.join(BASE, "proxy.json")
STATS_F = os.path.join(BASE, "logs", "bodyfetch_stats.log")

SLEEP = 2.5         # politeness between page loads
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"
BLOCK_TYPES = {"image", "font", "media", "stylesheet"}
# Drupal JS bundles are pure bandwidth (~650KB/page) for our purposes — the
# HTML is server-rendered. Blocking all scripts EXCEPT the Incapsula challenge
# JS cuts transfer to ~20KB/page (measured 2026-10-22) with 10/10 success.

def item_type(url):
    for t in ("release", "speech", "feature"):
        if f"/{t}/" in url:
            return t
    return "page"


def is_challenge(html):
    """Stub detection — NOT '_Incapsula_Resource' (legit pages load it too)."""
    if len(html) < 3000:
        return True
    if "Incapsula incident" in html:
        return True
    if "NOINDEX, NOFOLLOW" in html and len(html) < 10000:
        return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", default=os.path.join(BASE, "pending_pages.jsonl"))
    ap.add_argument("--limit", type=int, default=12)
    ap.add_argument("--time-budget", type=int, default=0,
                    help="stop starting new pages after N seconds (cron runner "
                         "kills scripts at ~120s — stay under it)")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    cfg = json.load(open(PROXY_F))
    sess = "s" + "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
    proxy = {
        "server": cfg["server"],
        "username": base64.b64decode(cfg["username_b64"]).decode(),
        "password": base64.b64decode(cfg["password_base_b64"]).decode()
        + f"_country-nz_session-{sess}_lifetime-30m",
    }

    # only status=="ok" counts as done; failed/challenged are transient
    done_urls = set()
    attempts = {}
    if os.path.exists(DONE_F):
        with open(DONE_F) as f:
            for line in f:
                try:
                    rec = json.loads(line)
                    if rec.get("status") == "ok":
                        done_urls.add(rec["url"])
                    else:
                        attempts[rec["url"]] = attempts.get(rec["url"], 0) + 1
                except Exception:
                    pass
    # URLs that failed 3+ times are dead (old Wayback-only paths) — stop retrying
    done_urls.update(u for u, n in attempts.items() if n >= 3)

    entries = []
    with open(args.queue) as f:
        for line in f:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec.get("url", "").startswith("http") and rec["url"] not in done_urls:
                entries.append(rec)

    if not entries:
        sys.exit(0)

    batch = entries[:args.limit]
    t0 = time.time()
    ok = challenged = failed = 0
    errors = []
    transfer = [0]

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True, proxy=proxy,
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx = browser.new_context(user_agent=UA)

        def on_response(resp):
            try:
                transfer[0] += int(resp.headers.get("content-length", 0) or 0)
            except Exception:
                pass

        def on_route(route):
            req = route.request
            if req.resource_type in BLOCK_TYPES:
                route.abort()
            elif req.resource_type == "script" and "_Incapsula_Resource" not in req.url:
                route.abort()
            else:
                route.continue_()

        ctx.route("**/*", on_route)
        page = ctx.new_page()
        page.on("response", on_response)

        for rec in batch:
            if args.time_budget and time.time() - t0 > args.time_budget:
                break
            url = rec["url"]
            status, path, sha, final_url = "failed", "", "", ""
            http_status = 0
            try:
                resp = page.goto(url, timeout=60000)
                final_url = page.url
                http_status = resp.status if resp else 0
                # poll until the JS challenge solves (typically 2-5s)
                html = ""
                for _ in range(15):
                    html = page.content()
                    if not is_challenge(html):
                        break
                    page.wait_for_timeout(1000)
                if http_status >= 400:
                    status = f"http_{http_status}"
                    failed += 1
                elif is_challenge(html):
                    status = "challenged"
                    challenged += 1
                else:
                    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                    d = os.path.join(PAGES, day)
                    os.makedirs(d, exist_ok=True)
                    slug = url.rstrip("/").split("/")[-1] or "index"
                    fname = (datetime.now(timezone.utc).strftime("%H%M%S")
                             + f"-{item_type(url)}-{slug}.html")
                    path = os.path.join(day, fname)
                    with open(os.path.join(PAGES, path), "w", encoding="utf-8") as f:
                        f.write(html)
                    sha = hashlib.sha256(html.encode()).hexdigest()
                    status = "ok"
                    ok += 1
            except Exception as e:
                status = f"failed: {e}"[:120]
                failed += 1
                errors.append(f"{url}: {e}"[:150])
            with open(DONE_F, "a") as f:
                f.write(json.dumps({
                    "url": url, "kind": rec.get("kind", ""),
                    "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "status": status, "path": path, "sha256": sha,
                    "final_url": final_url, "http_status": http_status,
                }, ensure_ascii=False) + "\n")
            time.sleep(SLEEP)
        browser.close()

    os.makedirs(os.path.dirname(STATS_F), exist_ok=True)
    with open(STATS_F, "a") as f:
        f.write(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} "
                f"queue={os.path.basename(args.queue)} ok={ok} challenged={challenged} "
                f"failed={failed} transfer_bytes={transfer[0]}\n")

    left = len(entries) - len(batch)
    # single transient failures are retried later — alert only on real trouble
    if failed >= 5 or (challenged and not ok):
        print(f"beehive bodyfetch: {ok} ok, {challenged} challenged, {failed} failed, "
              f"{left} left in queue. Errors: {'; '.join(errors)}", file=sys.stderr)
        sys.exit(1)
    if challenged:
        print(f"beehive bodyfetch: {ok} ok, {challenged} challenged (left for retry), "
              f"{left} left in queue", file=sys.stderr)
        sys.exit(1)
    # pure success: silent (empty stdout = no message)
    sys.exit(0)


if __name__ == "__main__":
    main()
