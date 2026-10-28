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

Budget/resume: the cron runner hard-kills scripts at ~120s (this script was
dead on arrival at daily scope — timed out every run 2026-10-23..27). It is
now deadline-bounded (--time-budget, default 80s) and resumable: the rolling
listing walk continues from a cursor in enum_state.json, discoveries are
flushed to the queue incrementally, and the CDX sweep runs at most once per
day per pattern at the END (archival delta — losing a run is harmless). Fresh
head pages (speeches?page=0 + /features) are re-fetched EVERY run so new items
are never delayed by the deep walk. A hard kill mid-unit loses at most the
in-flight fetch; state is saved per step.

URL normalization: CDX carries legacy '+slug' space-encoded URLs; live beehive
uses '-' and 404s every '+' form (measured 2026-10-28). Queued URLs are
normalized to '-' with the raw form kept in raw_url (approved fix 2026-10-28;
the raw URL is recorded, not discarded). Other old-style paths are queued
as-is; dead ones hit the bodyfetch retry cap and stop. Discrepancies (URL
style eras, redirects) are recorded, not fixed — raw only.

Exit semantics (cron no_agent): silent + exit 0; stderr + exit 1 ONLY when
the run achieved nothing AND had failures (systemic trouble). Transient
per-URL noise never alerts.
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
import urllib.parse
import urllib.request
from datetime import datetime, timezone

BASE = "/opt/data/beehive-scraper"
QUEUE_F = os.path.join(BASE, "backfill_queue.jsonl")
DONE_F = os.path.join(BASE, "done.jsonl")
STATE_F = os.path.join(BASE, "enum_state.json")
STATS_F = os.path.join(BASE, "logs", "enum_stats.log")
PAGES = os.path.join(BASE, "data", "pages")
PROXY_F = os.path.join(BASE, "proxy.json")
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"
SITE = "https://www.beehive.govt.nz"
CDX = "https://web.archive.org/cdx/search/cdx"
REFRESH_FEATURES = ["/feature/post-cab-press-conference"]
SPEECHES_LIST = "https://www.beehive.govt.nz/speeches?page="
FEATURES_LIST = "https://www.beehive.govt.nz/features"

GOTO_TIMEOUT = 25000      # ms; bounded so one unit cannot blow the budget
GOTO_TRIES = 2


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def norm(url):
    """Dedupe key only — not the URL we fetch."""
    path = url.split("://", 1)[-1]
    path = path.split("/", 1)[1] if "/" in path else path
    path = path.split("?")[0].split("#")[0]
    return urllib.parse.unquote(path).lower().rstrip("/")


def to_hyphen(url):
    """CDX '+slug' space-encoding -> live '-' form (raw kept by callers)."""
    head, sep, tail = url.partition("?")
    return head.replace("+", "-") + (sep + tail if sep else "")


def cdx_urls(pattern, timeout=90):
    q = urllib.parse.urlencode({
        "url": pattern, "output": "json", "fl": "original",
        "collapse": "urlkey", "filter": "statuscode:200", "limit": "50000"})
    req = urllib.request.Request(CDX + "?" + q, headers={"User-Agent": UA})
    data = json.loads(urllib.request.urlopen(req, timeout=timeout).read())
    out = []
    for row in data[1:]:
        u = row[0]
        path = u.split("://", 1)[-1]
        path = path.split("/", 1)[1] if "/" in path else path
        path = "/" + path.split("?")[0].split("#")[0]
        if path.startswith(("/speech", "/feature")):
            out.append(path)
    return out


def goto_retry(page, url, tries=GOTO_TRIES):
    """Navigation with retries — proxy tunnels fail transiently."""
    for i in range(tries):
        try:
            page.goto(url, timeout=GOTO_TIMEOUT)
            return
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(3)


def fetch_listing(page, url):
    """One listing page -> (links, ok). Raises on navigation failure."""
    goto_retry(page, url)
    html = ""
    for _ in range(10):
        html = page.content()
        if len(html) >= 3000 and "Incapsula incident" not in html:
            break
        page.wait_for_timeout(1000)
    links = re.findall(r'href="(/(?:speech|feature)/[^"?#]+)"', html)
    return links, bool(links) or "page=" not in url


def refresh_features(page, done_latest):
    """Re-fetch live feature pages; on sha change append a new done row.

    Returns (n_refreshed, n_changed, errors) — never exits; a transient
    failure is retried next run."""
    n_ok = n_changed = 0
    errors = []
    for path in REFRESH_FEATURES:
        prev = done_latest.get(path)
        url = SITE + path
        try:
            goto_retry(page, url)
            html = ""
            for _ in range(10):
                html = page.content()
                if len(html) >= 3000 and "Incapsula incident" not in html:
                    break
                page.wait_for_timeout(1000)
            sha = hashlib.sha256(html.encode()).hexdigest()
            n_ok += 1
            if prev and sha != prev:
                day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                d = os.path.join(PAGES, day)
                os.makedirs(d, exist_ok=True)
                fname = (f"{datetime.now(timezone.utc).strftime('%H%M%S')}"
                         f"-feature-{path.split('/')[-1]}.html")
                with open(os.path.join(d, fname), "w", encoding="utf-8") as f:
                    f.write(html)
                with open(DONE_F, "a") as f:
                    f.write(json.dumps({
                        "url": url, "kind": "feature-refresh",
                        "fetched_at": now_iso(),
                        "status": "ok", "path": os.path.join(day, fname),
                        "sha256": sha}, ensure_ascii=False) + "\n")
                n_changed += 1
        except Exception as e:
            errors.append(f"{path}: {e}"[:150])
    return n_ok, n_changed, errors


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--time-budget", type=int, default=80,
                    help="stop starting new work after N seconds (cron "
                         "runner kills scripts at ~120s — stay under it)")
    args = ap.parse_args()
    t0 = time.time()
    deadline = t0 + args.time_budget

    def over():
        return time.time() > deadline

    from playwright.sync_api import sync_playwright

    cfg = json.load(open(PROXY_F))
    sess = "s" + "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
    proxy = {"server": cfg["server"],
             "username": base64.b64decode(cfg["username_b64"]).decode(),
             "password": base64.b64decode(cfg["password_base_b64"]).decode()
             + f"_country-nz_session-{sess}_lifetime-30m"}

    # captured (ok) + attempts (transient, 3 strikes)
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

    state = {"speech_page": 1, "last_cdx": {}, "last_sweep": ""}
    if os.path.exists(STATE_F):
        try:
            state.update(json.load(open(STATE_F)))
        except Exception:
            pass

    def save_state():
        tmp = STATE_F + ".tmp"
        with open(tmp, "w") as f:
            json.dump(state, f)
        os.replace(tmp, STATE_F)

    seen = set()
    added = [0]
    fails = []
    swept = [0]

    def flush(path):
        """Queue one discovered path immediately (incremental)."""
        if not path.startswith("/"):
            return
        u_raw = path
        path = to_hyphen(path)
        full = SITE + path
        k = norm(path)
        if k in seen or full in done_ok or full in queued:
            return
        if attempts.get(full, 0) >= 3:
            return                      # dead URL: tried 3x, stop retrying
        seen.add(k)
        queued.add(full)
        rec = {"url": full, "kind": "backfill", "source": "browse+cdx"}
        if u_raw != path:
            rec["raw_url"] = SITE + u_raw
        with open(QUEUE_F, "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        added[0] += 1

    def walk(page, url, tag):
        try:
            links, got = fetch_listing(page, url)
            for l in links:
                flush(l)
            swept[0] += 1
            return got
        except Exception as e:
            fails.append(f"{tag}: {e}"[:150])
            return False

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

        # Phase A — fresh heads every run: newest speeches + features index
        walk(page, SPEECHES_LIST + "0", "head-speeches")
        walk(page, FEATURES_LIST, "head-features")

        # Phase B — rolling deep walk from cursor (speeches pages 1..N, 10/page)
        pnum = int(state.get("speech_page", 1))
        while not over():
            if not walk(page, SPEECHES_LIST + str(pnum), f"speeches?p={pnum}"):
                break                       # end of listing, or failure
            pnum += 1
            state["speech_page"] = pnum
            save_state()
        if pnum >= 28:                      # ~279 speeches / 10 per page
            state["speech_page"] = 1
            state["last_sweep"] = now_iso()
            save_state()

        # Phase C — feature body refresh (sha-change re-capture)
        f_ok, f_changed, f_err = refresh_features(page, done_latest)
        fails.extend(f_err)
        ctx.close()

    # Phase D — CDX sweep (archival delta, once/day per pattern, last on
    # budget: a missed run is harmless — the index only grows)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cdx_rows = 0
    for pattern in ("beehive.govt.nz/speech/*", "beehive.govt.nz/feature/*"):
        if state.get("last_cdx", {}).get(pattern) == today or over():
            continue
        try:
            found = cdx_urls(pattern, timeout=int(max(10, deadline - time.time())))
            for path in found:
                flush(path)
            cdx_rows += len(found)
            state.setdefault("last_cdx", {})[pattern] = today
            save_state()
        except Exception as e:
            fails.append(f"cdx {pattern}: {e}"[:150])

    os.makedirs(os.path.dirname(STATS_F), exist_ok=True)
    with open(STATS_F, "a") as f:
        f.write(f"{now_iso()} fetched={swept[0]} added={added[0]} "
                f"feature_ok={f_ok} feature_changed={f_changed} "
                f"cdx_rows={cdx_rows} resume_page={state.get('speech_page')} "
                f"secs={time.time()-t0:.0f}\n")

    # systemic trouble only: the run achieved nothing AND something failed
    if not added[0] and not f_ok and fails:
        print(f"beehive enum: 0 added, feature refresh failed, "
              f"{swept[0]} fetches. Errors: {'; '.join(fails)}",
              file=sys.stderr)
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
