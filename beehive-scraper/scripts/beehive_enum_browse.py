#!/usr/bin/env python3
"""Beehive speeches/features enumerator — closes the sitemap gap.

The sitemap contains ZERO /speech/ or /feature/ URLs. Three sources combined:

1. Live listing pages (via proxy+chromium, JS-challenged like everything else):
   /speeches?page=0..N (10/page, ~279 speeches, listing only reaches back to
   late 2023) and /features (single standing page).
2. Wayback CDX index (plain HTTP): every /speech/* and /feature/* URL ever
   archived — 13,665 + 784 rows — this is where pre-2023 speeches live.
   Enumerated, NOT captured (standing rule: Wayback captures are challenge
   stubs for beehive; we only use the index).
3. Feature refresh: /feature/post-cab-press-conference accumulates weekly
   transcripts but its feed date never changes — re-fetched every run and
   re-captured when the body sha changes (so extraction re-runs on it).

New URLs are appended to backfill_queue.jsonl (deduped against captured +
already queued) and drained by the regular backfill cron.

URL normalization (CDX rows are messy): strip scheme/host/:80, query and
fragment, unquote + lowercase for DEDUPE only — the queued URL keeps the raw
path. Old-style paths (/speech.foo+bar) are queued as-is; dead ones hit the
bodyfetch retry cap (3 attempts) and stop. Discrepancies (URL style eras,
redirects) are recorded, not fixed — raw only.

Exit semantics (cron no_agent): silent + exit 0; stderr + exit 1 on failure.
"""

import base64
import hashlib
import json
import os
import random
import re
import string
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

BASE = "/opt/data/beehive-scraper"
QUEUE_F = os.path.join(BASE, "backfill_queue.jsonl")
DONE_F = os.path.join(BASE, "done.jsonl")
PAGES = os.path.join(BASE, "data", "pages")
PROXY_F = os.path.join(BASE, "proxy.json")
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"
SITE = "https://www.beehive.govt.nz"
CDX = "https://web.archive.org/cdx/search/cdx"
REFRESH_FEATURES = ["/feature/post-cab-press-conference"]


def norm(url):
    """Dedupe key only — not the URL we fetch."""
    path = url.split("://", 1)[-1]
    path = path.split("/", 1)[1] if "/" in path else path
    path = path.split("?")[0].split("#")[0]
    return urllib.parse.unquote(path).lower().rstrip("/")


def cdx_urls(pattern):
    q = urllib.parse.urlencode({
        "url": pattern, "output": "json", "fl": "original",
        "collapse": "urlkey", "filter": "statuscode:200", "limit": "50000"})
    req = urllib.request.Request(CDX + "?" + q, headers={"User-Agent": UA})
    data = json.loads(urllib.request.urlopen(req, timeout=180).read())
    out = []
    for row in data[1:]:
        u = row[0]
        path = u.split("://", 1)[-1]
        path = path.split("/", 1)[1] if "/" in path else path
        path = "/" + path.split("?")[0].split("#")[0]
        if path.startswith(("/speech", "/feature")):
            out.append(path)
    return out


def goto_retry(page, url, tries=3):
    """Navigation with retries — proxy tunnels fail transiently."""
    for i in range(tries):
        try:
            page.goto(url, timeout=60000)
            return
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(5)


def browse_urls(page):
    """Live listing enumeration through the proxy+chromium."""
    found = []
    for base in ("https://www.beehive.govt.nz/speeches?page=",
                 "https://www.beehive.govt.nz/features"):
        n = 0
        while True:
            url = base + str(n) if "page=" in base else base
            goto_retry(page, url)
            for _ in range(15):
                html = page.content()
                if len(html) >= 3000 and "Incapsula incident" not in html:
                    break
                page.wait_for_timeout(1000)
            links = re.findall(r'href="(/(?:speech|feature)/[^"?#]+)"', html)
            if not links:
                break
            found.extend(links)
            if "page=" not in base:
                break
            n += 1
            if n > 60:
                break
            time.sleep(1.5)
    return found


def refresh_features(page, done_latest):
    """Re-fetch live feature pages; on sha change append a new done row."""
    for path in REFRESH_FEATURES:
        prev = done_latest.get(path)
        if not prev:
            continue
        url = SITE + path
        try:
            goto_retry(page, url)
            for _ in range(15):
                html = page.content()
                if len(html) >= 3000 and "Incapsula incident" not in html:
                    break
                page.wait_for_timeout(1000)
            sha = hashlib.sha256(html.encode()).hexdigest()
            if sha != prev:
                day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                d = os.path.join(PAGES, day)
                os.makedirs(d, exist_ok=True)
                fname = f"{datetime.now(timezone.utc).strftime('%H%M%S')}-feature-{path.split('/')[-1]}.html"
                with open(os.path.join(d, fname), "w", encoding="utf-8") as f:
                    f.write(html)
                with open(DONE_F, "a") as f:
                    f.write(json.dumps({
                        "url": url, "kind": "feature-refresh",
                        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        "status": "ok", "path": os.path.join(day, fname),
                        "sha256": sha}, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"feature refresh failed {path}: {e}", file=sys.stderr)
            sys.exit(1)


def main():
    from playwright.sync_api import sync_playwright

    cfg = json.load(open(PROXY_F))
    sess = "s" + "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
    proxy = {"server": cfg["server"],
             "username": base64.b64decode(cfg["username_b64"]).decode(),
             "password": base64.b64decode(cfg["password_base_b64"]).decode()
             + f"_country-nz_session-{sess}_lifetime-30m"}

    # captured (ok, latest sha per path) + queued
    done_ok = set()
    done_latest = {}
    attempts = {}
    with open(DONE_F) as f:
        for line in f:
            try:
                r = json.loads(line)
                if r.get("status") == "ok":
                    done_ok.add(r["url"])
                    done_latest[norm(r["url"])] = r.get("sha256", "")
                else:
                    attempts[r["url"]] = attempts.get(r["url"], 0) + 1
            except Exception:
                pass
    queued = set()
    if os.path.exists(QUEUE_F):
        with open(QUEUE_F) as f:
            for line in f:
                try:
                    queued.add(json.loads(line)["url"])
                except Exception:
                    pass

    urls = cdx_urls("beehive.govt.nz/speech/*") + cdx_urls("beehive.govt.nz/feature/*")
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            os.path.join(BASE, ".chromium-profile"), headless=True, proxy=proxy,
            user_agent=UA, args=["--disable-blink-features=AutomationControlled"])

        def on_route(route):
            req = route.request
            if req.resource_type in {"image", "font", "media", "stylesheet"}:
                route.abort()
            elif req.resource_type == "script" and "_Incapsula_Resource" not in req.url:
                route.abort()
            else:
                route.continue_()

        ctx.route("**/*", on_route)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        urls += browse_urls(page)
        refresh_features(page, done_latest)
        ctx.close()

    seen = set()
    added = 0
    with open(QUEUE_F, "a") as f:
        for u in urls:
            if not u.startswith("/"):
                continue
            # CDX carries legacy '+slug' space-encoding; live beehive uses
            # '-' and 404s every '+' form (measured 2026-10-28). Normalize at
            # the source; keep the raw form for provenance.
            u_raw = u
            u = u.replace("+", "-")
            full = SITE + u
            k = norm(u)
            if k in seen or full in done_ok or full in queued:
                continue
            if attempts.get(full, 0) >= 3:
                continue          # dead URL: tried 3x, stop retrying
            seen.add(k)
            rec = {"url": full, "kind": "backfill",
                   "source": "browse+cdx"}
            if u_raw != u:
                rec["raw_url"] = SITE + u_raw
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            added += 1

    if added:
        pass  # queue growth is normal — silent
    sys.exit(0)


if __name__ == "__main__":
    main()
