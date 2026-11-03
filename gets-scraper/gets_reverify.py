#!/usr/bin/env python3
"""GETS re-verify pass — tender pages change after capture (closing
dates pass, awards get posted, notices get amended or pulled). The tick
never re-fetches captured URLs, so those changes were invisible.

Same event model as court-scraper/reverify_courts.py: samples captured
tenders oldest-checked-first, emits change_events.jsonl events
(content_changed / removed / restored), never overwrites bytes.
"""
import argparse
import hashlib
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

BASE = "/opt/data/gets-scraper"
RECORDS_F = os.path.join(BASE, "records.jsonl")
EVENTS_F = os.path.join(BASE, "change_events.jsonl")
STATE_F = os.path.join(BASE, "reverify_state.json")

UA = ("Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 "
      "Firefox/128.0 (Query NZ corpus capture; contact arthur@betelgeuse.co.nz)")
SLEEP = 1.0


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fetch(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, b""


def store_bytes(rel, body):
    full = os.path.join(BASE, "data", rel)
    if os.path.exists(full):
        with open(full, "rb") as f:
            if f.read() == body:
                return rel
        stem, ext = os.path.splitext(rel)
        rel = f"{stem}-{hashlib.sha256(body).hexdigest()[:8]}{ext}"
        full = os.path.join(BASE, "data", rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "wb") as f:
        f.write(body)
    return rel


def semantic_sha(body):
    """Compare hash with per-request noise stripped (ASP.NET __VIEWSTATE /
    eventvalidation hidden inputs, clock ticks). Raw bytes are stored
    byte-exact and raw sha stays the artifact hash; this hash exists only
    so 'content_changed' means the PAGE changed, not the token."""
    t = body.decode("utf-8", errors="replace")
    t = re.sub(r'<input[^>]*type="hidden"[^>]*>', "", t, flags=re.I)
    t = re.sub(r'name="(?:__VIEWSTATE|__EVENTVALIDATION|__VIEWSTATEGENERATOR'
               r'|__EVENTTARGET|__EVENTARGUMENT)"[^>]*', "", t, flags=re.I)
    t = re.sub(r"\d{1,2}:\d{2}:\d{2}", "TIME", t)
    # GETS embeds per-request numeric tokens (measured: bare digit-runs
    # change on every fetch, same-length). Mask digit runs >= 4 so the
    # comparison reflects the page, not the anti-bot noise.
    t = re.sub(r"\d{4,}", "N", t)
    t = re.sub(r"\s+", " ", t)
    return hashlib.sha256(t.encode()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--time-budget", type=int, default=100)
    args = ap.parse_args()
    t0 = time.time()

    state = {}
    if os.path.exists(STATE_F):
        try:
            state = json.load(open(STATE_F))
        except ValueError:
            state = {}

    latest = {}
    with open(RECORDS_F) as f:
        for line in f:
            line = line.strip()
            if line:
                r = json.loads(line)
                if r.get("url") and r.get("sha256") and r.get("kind") == "tender_notice":
                    latest[r["url"]] = r

    urls = sorted(latest, key=lambda u: state.get(u, ""))
    random.Random(43).shuffle(urls)
    urls.sort(key=lambda u: state.get(u, ""))
    urls = urls[:args.limit]

    events = []
    for u in urls:
        if time.time() - t0 > args.time_budget:
            break
        rec = latest[u]
        time.sleep(SLEEP)
        try:
            status, body = fetch(u)
        except Exception as e:
            events.append({"url": u, "event": "reverify_error",
                           "detail": str(e)[:100], "detected_at": now_iso(),
                           "corpus": "gets"})
            state[u] = now_iso()
            continue
        prev = rec.get("sha256")
        # semantic comparison against the stored artifact — token churn is
        # not a content change
        stored_path = os.path.join(BASE, "data", rec.get("path", ""))
        if status == 200 and rec.get("path") and os.path.exists(stored_path):
            with open(stored_path, "rb") as f:
                if semantic_sha(f.read()) == semantic_sha(body):
                    state[u] = now_iso()
                    continue
        if status in (404, 410):
            events.append({"url": u, "event": "removed", "http_status": status,
                           "detected_at": now_iso(), "prev_sha256": prev,
                           "corpus": "gets", "rfx_id": rec.get("case_slug", "")})
        elif status == 200:
            new = hashlib.sha256(body).hexdigest()
            if new != prev:
                tag = hashlib.sha1(u.encode()).hexdigest()[:10]
                rel = store_bytes(os.path.join("pages", f"reverify-gets-{tag}.html"), body)
                events.append({"url": u, "event": "content_changed",
                               "detected_at": now_iso(), "prev_sha256": prev,
                               "new_sha256": new, "path": rel, "corpus": "gets",
                               "rfx_id": rec.get("case_slug", "")})
        else:
            events.append({"url": u, "event": "reverify_http",
                           "http_status": status, "detected_at": now_iso(),
                           "corpus": "gets"})
        state[u] = now_iso()

    if events:
        with open(EVENTS_F, "a") as f:
            for e in events:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
    with open(STATE_F, "w") as f:
        json.dump(state, f)
    kinds = {}
    for e in events:
        kinds[e["event"]] = kinds.get(e["event"], 0) + 1
    print(f"gets-reverify: checked={len(urls)} events={len(events)} {kinds}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
